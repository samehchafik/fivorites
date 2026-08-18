"""L'entraînement de la notation — les pages Training 1 et Training 2.

C'est l'exception assumée à « l'admin n'écrit pas » : elle écrit dans le schéma
`notation`, qui lui appartient le temps de l'entraînement — le barème s'édite
ici, les notes s'y accumulent, les poids s'y règlent. Elle n'écrit toujours
rien dans `sourcing`.

Phase 1 — stabiliser le barème. Une œuvre, un prompt éditable, deux juges :
OpenAI note, Haiku contre-note. Si les deux divergent au-delà du bruit, c'est
le prompt qui est ambigu — on le corrige et on rejoue. Chaque appel est stocké
avec l'empreinte du dossier ET du prompt : rien n'est comparable sans ça.

Phase 2 — régler les poids. La régression interne prédit les axes depuis
l'embedding du dossier ; on la confronte aux notes LLM. Divergence forte →
réentraîner (le bouton) ; divergence au niveau du bruit → les poids tiennent.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import math
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, status
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from fiv_admin.deps import Config, Conn, CurrentUser
from fiv_admin.dossier import build_dossier, load_fiche, load_seasons
from fiv_admin.embed import EMBEDDER, MAX_CHARS, embed_texts, etiquette, liberer_modeles
from fiv_admin.llm import (
    LOT_EMBEDDING,
    TARIF_EMBEDDING,
    LlmError,
    caption_openai,
    embed_openai,
    score_anthropic,
    score_openai,
)
from fiv_admin.media import DEFAULT_MEDIA, MEDIA
from fiv_admin.oeuvre import pivot
from fiv_admin.stills import select_images
from fiv_admin.weights import comparer_modeles as comparer_modeles_axe
from fiv_admin.weights import (
    diagnostic_visuels,
    predict,
    predictions_ridge,
    train_axis,
    voisins_cosinus,
)

log = logging.getLogger(__name__)

router = APIRouter()

# Le nom du « modèle » sous lequel les prédictions internes sont rangées dans
# `notation.score` — jamais mélangées aux notes LLM.
INTERNAL_MODEL = "interne-ridge"

# En dessous, entraîner n'a pas de sens : plus de bruit que de signal.
MIN_TRAINING_WORKS = 10


def _prompt_sha(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


async def _rubric(conn: Any, version: str) -> dict[str, Any]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "select version, prompt, axes, note, created_at"
            " from notation.rubric where version = %s",
            (version,),
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"barème inconnu : {version}")
    return row


async def _store_scores(
    conn: Any,
    *,
    oeuvre_id: int,
    scores: dict[str, dict[str, Any]],
    rubric_version: str,
    modele: str,
    input_sha256: str,
    prompt_sha256: str,
) -> None:
    async with conn.cursor() as cur:
        for axe, entry in scores.items():
            await cur.execute(
                """
                insert into notation.score
                    (oeuvre_id, axe, valeur, confiance, rubric_version, modele,
                     input_sha256, prompt_sha256)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    oeuvre_id,
                    axe,
                    entry.get("score"),
                    entry.get("confidence"),
                    rubric_version,
                    modele,
                    input_sha256,
                    prompt_sha256,
                ),
            )


def _gaps(
    left: dict[str, dict[str, Any]], right: dict[str, dict[str, Any]], axes: list[str]
) -> dict[str, Any]:
    """Les écarts par axe, et leur moyenne sur les axes notés des deux côtés."""
    per_axis: dict[str, float | None] = {}
    diffs: list[float] = []
    for axe in axes:
        a, b = left.get(axe, {}).get("score"), right.get(axe, {}).get("score")
        if a is None or b is None:
            per_axis[axe] = None
        else:
            gap = abs(float(a) - float(b))
            per_axis[axe] = gap
            diffs.append(gap)
    return {
        "perAxis": per_axis,
        "mean": round(sum(diffs) / len(diffs), 2) if diffs else None,
        "scored": len(diffs),
    }


# ---------------------------------------------------------------- les visuels


async def _caption_missing(
    conn: Any, settings: Any, work_id: int, oeuvre_id: int, *, univers: str = "series"
) -> dict[str, Any]:
    """Légende ce qui ne l'est pas encore, et seulement ça.

    Le cœur du légendage, partagé entre le bouton et le chemin automatique :
    sélection déterministe des visuels, un appel vision pour les images
    inconnues, insertion figée. `total` à 0 = rien à légender (série non
    collectée, ou brut sans visuel). Les erreurs vision remontent en LlmError.

    Deux identifiants, et ce n'est pas une redondance : `work_id` lit le brut
    (c'est ce que TMDB a servi), `oeuvre_id` écrit la légende (c'est notre
    pivot). Voir [`oeuvre.py`](../oeuvre.py).
    """
    model = settings.openai_model
    bilan = {"captioned": 0, "already": 0, "total": 0, "model": model}
    fiche = await load_fiche(conn, work_id, univers=univers)
    if fiche is None:
        return bilan
    saisons = [] if univers != "series" else await load_seasons(conn, work_id)
    images = select_images(fiche["payload"], saisons)
    if not images:
        return bilan

    async with conn.cursor() as cur:
        await cur.execute(
            "select url from notation.media_caption where oeuvre_id = %s", (oeuvre_id,)
        )
        known = {row[0] for row in await cur.fetchall()}
    fresh = [image for image in images if image["url"] not in known]

    captioned = 0
    if fresh:
        async with httpx.AsyncClient() as http:
            result = await caption_openai(
                http, api_key=settings.openai_api_key, model=model, images=fresh
            )
        model = result["model"]
        async with conn.cursor() as cur:
            for image, caption in zip(fresh, result["captions"], strict=True):
                if not caption:
                    continue
                await cur.execute(
                    """
                    insert into notation.media_caption
                        (oeuvre_id, url, kind, label, caption, modele)
                    values (%s, %s, %s, %s, %s, %s)
                    on conflict (oeuvre_id, url) do nothing
                    """,
                    (oeuvre_id, image["url"], image["kind"], image["label"], caption, model),
                )
                captioned += 1

    return {
        "captioned": captioned,
        "already": len(images) - len(fresh),
        "total": len(images),
        "model": model,
    }


async def _auto_captions(
    conn: Any, settings: Any, work_id: int, oeuvre_id: int, *, univers: str = "series"
) -> None:
    """Le chemin automatique : les légendes se créent à la première lecture.

    La donnée visuelle ne bouge pratiquement pas — une fois payée, la légende
    est là pour toujours ; il n'y a donc aucune raison d'attendre un clic.
    Silencieux par choix : sans clé OpenAI ou si la vision tousse, le dossier
    doit quand même se lire — simplement sans section MEDIA.
    """
    if not settings.openai_api_key:
        return
    with contextlib.suppress(LlmError):
        await _caption_missing(conn, settings, work_id, oeuvre_id, univers=univers)


async def works_a_noter(
    conn: Any,
    rubric_version: str,
    limit: int,
    *,
    inedites: bool = False,
    filtres: bool = True,
    rejouer: bool = False,
    univers: str = "series",
) -> list[dict[str, Any]]:
    """Les œuvres collectées qu'aucun juge n'a encore notées sur ce barème.

    « Pas encore notées » se lit dans `notation.training_run` : une œuvre qui a
    déjà un essai sur ce barème est écartée, quel que soit son contenu. C'est
    le journal qui fait foi, pas `notation.score` — l'atelier affiche le
    journal, et une liste qui proposerait une œuvre déjà visible comme notée à
    l'écran serait incompréhensible.

    « Sur ce barème », et c'est le second point : l'entraînement des poids
    filtre par `rubric_version`, donc un essai rendu sous un barème précédent
    ne nourrit pas le suivant. Une œuvre déjà jugée en v1 reste donc candidate
    pour v2, et la colonne `deja` le dit ; `inedites` restreint aux œuvres
    sans aucun essai, quand on cherche à élargir plutôt qu'à compléter.

    `rejouer` lève cette exclusion et reprend tout, essais compris. Le journal
    étant fait d'ajouts, rien n'est écrasé : le nouvel essai s'empile à côté
    de l'ancien, et c'est le plus récent que l'atelier montre. C'est ainsi
    qu'on rejoue un lot après avoir corrigé un prompt ou ajouté les légendes,
    sans avoir à vider quoi que ce soit — mais chaque œuvre est repayée.

    L'ordre est celui du catalogue : popularité d'abord, note des votants pour
    départager. Entraîner sur les œuvres les plus vues n'est pas un biais de
    confort — ce sont celles dont les dossiers sont les plus fournis (Wikipédia,
    synopsis d'épisodes, visuels), donc celles qui apprennent le plus par appel
    payé. La longue traîne obscure viendra quand le barème tiendra.

    `filtres` exige une affiche, et rien d'autre. Filtrer aussi sur le
    descriptif a été essayé puis retiré : le champ est mal calibré pour cet
    usage — présent ou absent selon la langue interrogée, il écartait des
    œuvres notables et en laissait passer d'autres sans matière. Le vrai
    garde-fou reste en aval, sur la taille du dossier assemblé, qui mesure ce
    qui compte vraiment plutôt qu'un champ pris isolément.

    La lecture passe par `admin.tv_card`, comme la grille. Interroger le brut
    obligeait à déplier le JSON de chaque fiche collectée pour n'en garder que
    vingt : quelques secondes d'attente sur un simple aperçu. La contrepartie
    est celle de la grille — une série fraîchement collectée n'apparaît
    qu'après `catalog refresh`.
    """
    carte = CARTE_PAR_UNIVERS.get(univers)
    if carte is None:
        raise LlmError(f"univers inconnu : {univers} — attendus {sorted(CARTE_PAR_UNIVERS)}")
    async with conn.cursor(row_factory=dict_row) as cur:
        # Le nom de la vue est interpolé, pas paramétré — PostgreSQL n'accepte
        # pas de table en paramètre. Il ne vient jamais de l'extérieur :
        # `CARTE_PAR_UNIVERS` est une table close, vérifiée juste au-dessus.
        await cur.execute(
            f"""
            -- La jointure sur `sourcing.oeuvre` n'est pas décorative : c'est
            -- elle qui écarte les fiches sans pivot, donc non collectables —
            -- et c'est par `oeuvre_id` que le journal des essais se lit
            -- désormais. Une œuvre collectée a toujours son pivot (la collecte
            -- le crée), une œuvre qui n'en a pas ne peut de toute façon pas
            -- être notée.
            with page as (
                select v.id                                as id_tmdb,
                       o.id                                as oeuvre_id,
                       coalesce(v.name, v.original_name)   as titre,
                       c.popularity                        as popularity,
                       v.vote_average                      as note
                from {carte} v
                join tmdb_catalog c on c.univers = %(univers)s and c.id = v.id
                join sourcing.oeuvre o on o.univers = %(univers)s and o.id_tmdb = v.id
                where (not %(filtres)s or nullif(v.poster_path, '') is not null)
                  and (%(rejouer)s or not exists (
                      select 1 from notation.training_run t
                      where t.oeuvre_id = o.id and t.rubric_version = %(rubric)s
                  ))
                  and (not %(inedites)s or not exists (
                      select 1 from notation.training_run t where t.oeuvre_id = o.id
                  ))
                order by c.popularity desc nulls last, v.vote_average desc nulls last
                limit %(limit)s
            )
            -- L'inventaire des barèmes déjà vus ne sert qu'à l'affichage : il
            -- se calcule sur la page retenue, pas sur les vingt-huit mille
            -- candidates qu'on vient d'écarter.
            select p.*, (
                select array_agg(distinct t.rubric_version order by t.rubric_version)
                from notation.training_run t where t.oeuvre_id = p.oeuvre_id
            ) as deja
            from page p
            order by popularity desc nulls last, note desc nulls last
            """,
            {
                "rubric": rubric_version,
                "inedites": inedites,
                "filtres": filtres,
                "rejouer": rejouer,
                "limit": limit,
                "univers": univers,
            },
        )
        return list(await cur.fetchall())


class EncodeurIndisponible(RuntimeError):
    """L'encodeur de production n'a répondu pour aucune œuvre.

    Distincte d'un échec d'entraînement : les notes sont là, les dossiers
    aussi, seul l'encodage a manqué. La conduite à tenir est d'attendre et de
    relancer, pas de noter davantage d'œuvres.
    """

    def __init__(self, etiquette: str, ecartees: int) -> None:
        super().__init__(
            f"aucune œuvre encodée par {etiquette} — {ecartees} rendue(s) par le secours"
            " local, dont les vecteurs vivent dans un autre espace. Entraînement annulé."
        )


class NonCollectee(RuntimeError):
    """Aucune fiche collectée pour cette série : il n'y a rien à noter."""


class DossierMaigre(RuntimeError):
    """Le dossier existe mais ne porte pas de quoi juger.

    Distincte de `NonCollectee` parce que la conduite à tenir diffère : l'une
    demande une collecte, l'autre un enrichissement.
    """

    def __init__(self, chars: int) -> None:
        super().__init__(f"dossier trop maigre ({chars} caractères)")
        self.chars = chars


async def note_work(
    conn: Any,
    settings: Any,
    *,
    id_tmdb: int,
    rubric_version: str,
    prompt: str,
    axes: list[str],
    captions: bool = False,
    univers: str = "series",
) -> dict[str, Any]:
    """Note une œuvre et journalise l'essai — le chemin commun au bouton et au lot.

    Une seule fonction pour les deux entrées : la page Training 1 note une
    œuvre à la fois, la commande `training note` en enchaîne cinquante, et il
    serait fâcheux que la seconde produise des notes subtilement différentes
    de la première. Même dossier, mêmes juges, même provenance.

    Les erreurs remontent telles quelles — `NonCollectee`, `DossierMaigre`,
    `LlmError` — pour que chaque appelant décide : la route en fait des codes
    HTTP, le lot saute l'œuvre et poursuit.
    """
    # Le pivot, résolu une fois pour tout l'essai : tout ce qui s'écrit
    # ci-dessous se range sous lui, et une œuvre sans pivot n'est pas
    # collectée — donc pas notable. `SansPivot` remonte comme les autres.
    oeuvre_id = await pivot(conn, id_tmdb, univers=univers)

    if captions:
        # Quand on les demande, les légendes passent AVANT le dossier : le juge
        # doit lire la section MEDIA, pas découvrir qu'elle manquait une fois
        # la note rendue. Éteint par défaut — un appel de vision par œuvre
        # coûte plus cher que la notation elle-même, et l'entraînement se règle
        # d'abord sur du texte.
        await _auto_captions(conn, settings, id_tmdb, oeuvre_id, univers=univers)

    built = await build_dossier(conn, id_tmdb, oeuvre_id=oeuvre_id, univers=univers)
    if built is None:
        raise NonCollectee(f"œuvre {id_tmdb} non collectée en {univers}")
    if not built["enough"]:
        raise DossierMaigre(built["chars"])

    async with httpx.AsyncClient() as http:
        calls = [
            score_openai(
                http,
                api_key=settings.openai_api_key,
                model=settings.openai_model,
                prompt=prompt,
                dossier=built["text"],
                axes=axes,
            )
        ]
        if settings.anthropic_api_key:
            calls.append(
                score_anthropic(
                    http,
                    api_key=settings.anthropic_api_key,
                    model=settings.anthropic_model,
                    prompt=prompt,
                    dossier=built["text"],
                    axes=axes,
                )
            )
        results = await asyncio.gather(*calls)

    openai_result = results[0]
    haiku_result = results[1] if len(results) > 1 else None

    prompt_sha = _prompt_sha(prompt)
    for result in results:
        await _store_scores(
            conn,
            oeuvre_id=oeuvre_id,
            scores=result["scores"],
            rubric_version=rubric_version,
            modele=result["model"],
            input_sha256=built["sha256"],
            prompt_sha256=prompt_sha,
        )

    # Le journal de bord : l'essai entier sur une ligne — prompt en clair,
    # fiche brute référencée, verdicts côte à côte. `notation.score` reste la
    # table de travail des poids ; celle-ci est celle qu'on relit.
    async with conn.cursor() as cur:
        await cur.execute(
            """
            insert into notation.training_run
                (oeuvre_id, raw_source_id, rubric_version, prompt, dossier_sha256,
                 openai, claude, claude_at)
            values (%(id)s, %(raw)s, %(rubric)s, %(prompt)s, %(sha)s,
                    %(openai)s, %(claude)s,
                    case when %(claude)s::jsonb is not null then now() end)
            returning id
            """,
            {
                "id": oeuvre_id,
                "raw": built["rawSourceId"],
                "rubric": rubric_version,
                "prompt": prompt,
                "sha": built["sha256"],
                "openai": Jsonb(openai_result),
                "claude": Jsonb(haiku_result) if haiku_result else None,
            },
        )
        run_id = (await cur.fetchone())[0]

    return {"runId": run_id, "built": built, "openai": openai_result, "haiku": haiku_result}


# ---------------------------------------------------------------- le dossier


def _univers(media: str) -> str:
    """`tv`/`movie` → `series`/`movies`. Liste fermée : la valeur vient de HTTP.

    Sans ce passage, l'atelier construisait toujours un dossier de série, donc
    cherchait la fiche d'un film sous `kind = 'tv'` et n'en trouvait aucune —
    l'onglet Training s'affichait vide en univers films.
    """
    if media not in MEDIA:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"univers inconnu : {media} (attendus : {', '.join(MEDIA)})",
        )
    return MEDIA[media].univers


@router.get("/training/works/{work_id}/dossier")
async def dossier(
    user: CurrentUser, conn: Conn, work_id: int, media: str = DEFAULT_MEDIA
) -> dict[str, Any]:
    """Le dossier tel qu'il est en base — aucune dépense déclenchée par une
    simple lecture. Les légendes visuelles se demandent explicitement, par le
    bouton : ouvrir une fiche ne doit jamais coûter un appel de vision.

    `media` qualifie l'identifiant : les deux catalogues TMDB se chevauchent,
    et 550 désigne un film comme une série."""
    built = await build_dossier(conn, work_id, univers=_univers(media))
    if built is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"aucune fiche collectée pour {work_id} en {media}"
            " — impossible de construire un dossier.",
        )
    return built


@router.post("/training/works/{work_id}/captions")
async def caption_work(
    user: CurrentUser, conn: Conn, settings: Config, work_id: int, media: str = DEFAULT_MEDIA
) -> dict[str, Any]:
    """Le légendage à la demande — utile après une re-collecte, pour ne pas
    attendre la prochaine lecture de dossier.

    Idempotent par construction : une image déjà légendée n'est jamais
    renvoyée au modèle — la légende est payée une fois, puis relue par le
    dossier pour toujours.
    """
    if not settings.openai_api_key:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "OPENAI_API_KEY doit être renseignée dans le .env de l'admin "
            "pour légender les visuels.",
        )
    univers = _univers(media)
    fiche = await load_fiche(conn, work_id, univers=univers)
    if fiche is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"œuvre {work_id} non collectée en {media}")
    # Un film n'a pas de saisons : la liste vide vaut « pas de stills », et
    # `select_images` retombe alors sur les seuls backdrops de la fiche.
    saisons = [] if univers != "series" else await load_seasons(conn, work_id)
    if not select_images(fiche["payload"], saisons):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "aucun visuel dans le brut collecté — ni backdrop sur la fiche, "
            "ni still d'épisode sur les saisons en-US.",
        )

    try:
        bilan = await _caption_missing(
            conn,
            settings,
            work_id,
            await pivot(conn, work_id, univers=univers),
            univers=univers,
        )
    except LlmError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return {"id": work_id, **bilan}


# ---------------------------------------------------------------- le barème


class RubricIn(BaseModel):
    version: str = Field(min_length=1, max_length=60)
    prompt: str = Field(min_length=50)
    axes: list[str] = Field(min_length=1, max_length=16)
    note: str | None = None


@router.get("/training/rubrics")
async def rubrics(user: CurrentUser, conn: Conn) -> list[dict[str, Any]]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "select version, prompt, axes, note, created_at"
            " from notation.rubric order by created_at desc"
        )
        return list(await cur.fetchall())


@router.post("/training/rubrics", status_code=status.HTTP_201_CREATED)
async def save_rubric(user: CurrentUser, conn: Conn, body: RubricIn) -> dict[str, Any]:
    """Une nouvelle version de barème. Jamais d'écrasement : changer une ancre
    change toutes les notes qui en découlent, la version EST la provenance."""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            insert into notation.rubric (version, prompt, axes, note)
            values (%s, %s, %s, %s)
            on conflict (version) do nothing
            returning version
            """,
            (body.version, body.prompt, Jsonb(body.axes), body.note),
        )
        created = await cur.fetchone()
    if created is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"le barème {body.version} existe déjà — choisir un nouveau nom de version.",
        )
    return {"version": body.version}


# ---------------------------------------------------------------- phase 1


class Phase1In(BaseModel):
    id: int
    rubricVersion: str
    # L'univers de l'œuvre. Un identifiant TMDB seul ne désigne rien : les
    # deux catalogues se chevauchent, et 550 est un film comme une série.
    media: str = DEFAULT_MEDIA
    # Le prompt réellement envoyé — celui de l'éditeur, sauvé ou non. Son
    # empreinte accompagne chaque note : un essai non sauvé reste traçable.
    prompt: str = Field(min_length=50)
    axes: list[str] = Field(min_length=1, max_length=16)


@router.post("/training/phase1")
async def phase1(user: CurrentUser, conn: Conn, settings: Config, body: Phase1In) -> dict[str, Any]:
    """Une œuvre, un juge OpenAI — et un contre-juge si sa clé est là.

    Le contre-jugement automatique (Haiku) est **facultatif** : sans clé
    Anthropic, il se fait à la main — le bouton du front copie consigne +
    dossier pour claude.ai, et la contre-note se saisit via `/training/manual`.
    Même boucle, même provenance ; seul l'exécutant change.
    """
    if not settings.openai_api_key:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "OPENAI_API_KEY doit être renseignée dans le .env de l'admin "
            "pour lancer un entraînement.",
        )
    await _rubric(conn, body.rubricVersion)

    try:
        essai = await note_work(
            conn,
            settings,
            id_tmdb=body.id,
            rubric_version=body.rubricVersion,
            prompt=body.prompt,
            axes=body.axes,
            univers=_univers(body.media),
        )
    except NonCollectee as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except DossierMaigre as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"dossier trop maigre ({exc.chars} caractères) — noter cette série "
            "produirait des nombres sans valeur. L'enrichir d'abord (enrich --id).",
        ) from exc
    except LlmError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    built, openai_result, haiku_result = essai["built"], essai["openai"], essai["haiku"]
    return {
        "id": body.id,
        "runId": essai["runId"],
        "dossier": {key: built[key] for key in ("sha256", "chars", "sections", "title")},
        "openai": openai_result,
        "haiku": haiku_result,
        "gaps": (
            _gaps(openai_result["scores"], haiku_result["scores"], body.axes)
            if haiku_result
            else None
        ),
    }


class ManualIn(BaseModel):
    id: int
    rubricVersion: str
    # L'univers de l'œuvre. Un identifiant TMDB seul ne désigne rien : les
    # deux catalogues se chevauchent, et 550 est un film comme une série.
    media: str = DEFAULT_MEDIA
    prompt: str = Field(min_length=50)
    # La contre-note saisie à la main — obtenue en collant consigne + dossier
    # dans claude.ai. `score` null = « le contre-juge ne sait pas », comme
    # pour les juges automatiques.
    scores: dict[str, dict[str, float | int | None]]
    # L'essai auquel cette contre-note répond, si la page s'en souvient. Sans
    # lui (page rechargée entre-temps), le dernier essai de la série sur ce
    # même prompt fait foi.
    runId: int | None = None


@router.post("/training/manual")
async def manual_scores(
    user: CurrentUser, conn: Conn, settings: Config, body: ManualIn
) -> dict[str, Any]:
    """Enregistre une contre-note faite à la main, avec la même provenance
    qu'un appel automatique : empreinte du dossier, empreinte du prompt."""
    await _rubric(conn, body.rubricVersion)
    univers = _univers(body.media)
    oeuvre_id = await pivot(conn, body.id, univers=univers)
    built = await build_dossier(conn, body.id, oeuvre_id=oeuvre_id, univers=univers)
    if built is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"œuvre {body.id} non collectée")

    cleaned = {
        axe: {
            "score": (
                int(min(10, max(1, round(entry["score"]))))
                if isinstance(entry.get("score"), int | float)
                else None
            ),
            "confidence": entry.get("confidence"),
        }
        for axe, entry in body.scores.items()
    }
    await _store_scores(
        conn,
        oeuvre_id=oeuvre_id,
        scores=cleaned,
        rubric_version=body.rubricVersion,
        modele="claude-web-manuel",
        input_sha256=built["sha256"],
        prompt_sha256=_prompt_sha(body.prompt),
    )

    # Le journal : la contre-note rejoint son essai. Trois chemins, dans
    # l'ordre — l'essai désigné, sinon le dernier essai de ce prompt encore
    # sans contre-note, sinon une ligne nouvelle (contre-note sans essai
    # OpenAI préalable : autorisé, le journal le montre tel quel).
    claude_json = Jsonb({"model": "claude-web-manuel", "scores": cleaned})
    async with conn.cursor() as cur:
        run_id: int | None = None
        if body.runId is not None:
            await cur.execute(
                "update notation.training_run set claude = %s, claude_at = now()"
                " where id = %s and oeuvre_id = %s returning id",
                (claude_json, body.runId, oeuvre_id),
            )
            row = await cur.fetchone()
            run_id = row[0] if row else None
        if run_id is None:
            await cur.execute(
                """
                update notation.training_run set claude = %(claude)s, claude_at = now()
                where id = (
                    select id from notation.training_run
                    where oeuvre_id = %(id)s and prompt = %(prompt)s and claude is null
                    order by created_at desc limit 1
                )
                returning id
                """,
                {"claude": claude_json, "id": oeuvre_id, "prompt": body.prompt},
            )
            row = await cur.fetchone()
            run_id = row[0] if row else None
        if run_id is None:
            await cur.execute(
                """
                insert into notation.training_run
                    (oeuvre_id, raw_source_id, rubric_version, prompt, dossier_sha256,
                     claude, claude_at)
                values (%s, %s, %s, %s, %s, %s, now())
                returning id
                """,
                (
                    oeuvre_id,
                    built["rawSourceId"],
                    body.rubricVersion,
                    body.prompt,
                    built["sha256"],
                    claude_json,
                ),
            )
            run_id = (await cur.fetchone())[0]

    return {"stored": len(cleaned), "modele": "claude-web-manuel", "runId": run_id}


@router.get("/training/works/{work_id}/runs")
async def work_runs(
    user: CurrentUser, conn: Conn, work_id: int, limit: int = 10, media: str = DEFAULT_MEDIA
) -> list[dict[str, Any]]:
    """Les derniers essais du journal, le plus récent d'abord.

    C'est ce qui rend les deux pages Training rechargeables : ni les verdicts
    ni le vecteur généré ne vivent dans l'état du navigateur, ils se relisent
    d'ici.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select id, rubric_version, prompt, dossier_sha256, openai, claude,
                   interne, created_at, claude_at, interne_at
            from notation.training_run
            where oeuvre_id = %s order by created_at desc limit %s
            """,
            (await pivot(conn, work_id, univers=_univers(media)), min(max(limit, 1), 50)),
        )
        rows = await cur.fetchall()
    return [
        {
            "id": row["id"],
            "rubricVersion": row["rubric_version"],
            "prompt": row["prompt"],
            "dossierSha256": row["dossier_sha256"],
            "openai": row["openai"],
            "claude": row["claude"],
            "interne": row["interne"],
            "createdAt": row["created_at"],
            "claudeAt": row["claude_at"],
            "interneAt": row["interne_at"],
        }
        for row in rows
    ]


@router.get("/training/works/{work_id}/scores")
async def work_scores(
    user: CurrentUser, conn: Conn, work_id: int, media: str = DEFAULT_MEDIA
) -> list[dict[str, Any]]:
    """L'historique des notes d'une œuvre — tous modèles, tous barèmes."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select axe, valeur, confiance, rubric_version, modele, scored_at
            from notation.score where oeuvre_id = %s
            order by scored_at desc, axe
            limit 400
            """,
            (await pivot(conn, work_id, univers=_univers(media)),),
        )
        return list(await cur.fetchall())


# ---------------------------------------------------------------- phase 2


async def _lire_cache(conn: Any, oeuvre_id: int | None, sha: str, label: str) -> list[float] | None:
    if oeuvre_id is None:
        return None
    async with conn.cursor() as cur:
        await cur.execute(
            "select vector from notation.embedding"
            " where oeuvre_id = %s and input_sha256 = %s and embedder = %s",
            (oeuvre_id, sha, label),
        )
        row = await cur.fetchone()
    return row[0] if row is not None else None


async def _ranger_vecteur(
    conn: Any, oeuvre_id: int | None, sha: str, label: str, vector: list[float]
) -> None:
    # Sans pivot, pas de cache : la table le porte en clé. Le vecteur est rendu
    # quand même — le cas ne se présente que pour une fiche collectée avant le
    # lot 12 et jamais revue depuis.
    if oeuvre_id is None:
        return
    async with conn.cursor() as cur:
        await cur.execute(
            """
            insert into notation.embedding (oeuvre_id, input_sha256, embedder, vector)
            values (%s, %s, %s, %s) on conflict do nothing
            """,
            (oeuvre_id, sha, label, Jsonb(vector)),
        )


async def encoder_dossier(
    conn: Any, settings: Any, built: dict[str, Any]
) -> tuple[list[float], str]:
    """Le vecteur du dossier ET l'étiquette de l'encodeur qui l'a produit.

    L'étiquette est rendue parce qu'elle décide de ce qu'on a le droit de
    faire du vecteur. L'encodeur de production peut être une API ; quand elle
    ne répond pas, le modèle local prend le relais — mais son vecteur vit dans
    un tout autre espace. Le servir à des poids entraînés sur l'API rendrait
    six nombres plausibles et faux, sans qu'aucune erreur ne se lève.

    D'où la règle : le secours **sert l'affichage, jamais l'entraînement ni la
    prédiction**. Les appelants comparent l'étiquette rendue à celle de
    production et écartent ce qui ne correspond pas. Un catalogue qui refuserait
    d'avancer parce qu'une API tousse serait pire qu'un vecteur dégradé et
    correctement étiqueté.

    Le cache reste la première réponse dans tous les cas : un dossier inchangé
    ne se réencode pas, et l'API ne se repaie pas.
    """
    oeuvre_id, sha = built.get("oeuvreId"), built["sha256"]
    label = etiquette(settings.embedder)

    en_cache = await _lire_cache(conn, oeuvre_id, sha, label)
    if en_cache is not None:
        return en_cache, label

    api = _encodeur_api(settings.embedder)
    if api is not None and settings.openai_api_key:
        nom, dims = api
        try:
            async with httpx.AsyncClient() as http:
                vecteurs = await embed_openai(
                    http,
                    api_key=settings.openai_api_key,
                    model=nom,
                    textes=[built["text"][:MAX_CHARS]],
                    dimensions=dims,
                )
            await _ranger_vecteur(conn, oeuvre_id, sha, label, vecteurs[0])
            return vecteurs[0], label
        except LlmError:
            # Journalisé, pas propagé : la suite bascule sur le secours, et
            # c'est l'étiquette rendue qui dira aux appelants de s'en méfier.
            log.warning("encodeur %s indisponible — secours local", settings.embedder)
    elif api is not None:
        log.warning("encodeur %s demandé sans OPENAI_API_KEY — secours local", settings.embedder)

    secours = EMBEDDER if api is not None else label
    en_cache = await _lire_cache(conn, oeuvre_id, sha, secours)
    if en_cache is not None:
        return en_cache, secours

    # `to_thread` : l'inférence ONNX est du calcul bloquant, et la tenir dans
    # la boucle d'événements figerait l'API pendant tout un entraînement.
    vectors = await asyncio.to_thread(
        embed_texts, [built["text"]], cache_dir=settings.embed_cache_dir
    )
    await _ranger_vecteur(conn, oeuvre_id, sha, secours, vectors[0])
    return vectors[0], secours


async def _embedding(conn: Any, settings: Any, built: dict[str, Any]) -> list[float]:
    """Le vecteur seul, pour les appelants qui n'ont pas à trancher l'espace."""
    vecteur, _ = await encoder_dossier(conn, settings, built)
    return vecteur


def _predict_all(vector: list[float], weights: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Le vecteur de goût prédit par les poids, axe par axe."""
    return {
        axe: {
            "score": predict(vector, row["intercept"], row["coef"]),
            "trainedOn": row["trainedOn"],
            "maeFit": row["maeFit"],
            "maeCv": row.get("maeCv"),
        }
        for axe, row in weights.items()
    }


async def _store_internal(
    conn: Any,
    *,
    oeuvre_id: int,
    internal: dict[str, Any],
    rubric_version: str,
    prompt: str,
    dossier_sha256: str,
    raw_source_id: int | None,
) -> int:
    """Écrit le vecteur généré dans `score` et dans le journal de l'essai.

    L'essai visé est le plus récent de l'œuvre sur ce barème ; sans essai
    préalable, une ligne naît pour l'accueillir. `interne_at` date la
    génération et non l'essai : les poids ont pu changer entre les deux.
    """
    await _store_scores(
        conn,
        oeuvre_id=oeuvre_id,
        scores={
            axe: {"score": entry["score"], "confidence": None} for axe, entry in internal.items()
        },
        rubric_version=rubric_version,
        modele=INTERNAL_MODEL,
        input_sha256=dossier_sha256,
        prompt_sha256=_prompt_sha(prompt),
    )

    interne_json = Jsonb(internal)
    async with conn.cursor() as cur:
        await cur.execute(
            """
            update notation.training_run set interne = %(interne)s, interne_at = now()
            where id = (
                select id from notation.training_run
                where oeuvre_id = %(id)s and rubric_version = %(rubric)s
                order by created_at desc limit 1
            )
            returning id
            """,
            {"interne": interne_json, "id": oeuvre_id, "rubric": rubric_version},
        )
        row = await cur.fetchone()
        if row is None:
            await cur.execute(
                """
                insert into notation.training_run
                    (oeuvre_id, raw_source_id, rubric_version, prompt, dossier_sha256,
                     interne, interne_at)
                values (%s, %s, %s, %s, %s, %s, now())
                returning id
                """,
                (oeuvre_id, raw_source_id, rubric_version, prompt, dossier_sha256, interne_json),
            )
            row = await cur.fetchone()
    return row[0]


class TrainIn(BaseModel):
    rubricVersion: str


# Les encodeurs mis en concurrence par `training encodeurs`. Tous à contexte
# long sauf le dernier, gardé comme témoin : il est réputé meilleur sur les
# classements publics mais ne lit que 512 tokens, et c'est précisément
# l'hypothèse qu'on veut tester — la fenêtre pèse-t-elle plus que la qualité
# brute de la représentation ?
#
# Les classements publics mesurent de la recherche documentaire ; notre tâche
# est une régression linéaire vers six axes de goût. Rien ne garantit que
# l'ordre se transpose, d'où cette comparaison sur les notes réelles.
ENCODEURS_CANDIDATS = (
    "jinaai/jina-embeddings-v2-small-en",
    "nomic-ai/nomic-embed-text-v1.5-Q",
    "jinaai/jina-embeddings-v2-base-en",
    "BAAI/bge-small-en-v1.5",
)


def _encodeur_api(modele: str) -> tuple[str, int | None] | None:
    """Découpe `openai/text-embedding-3-large@512`, ou None si c'est un modèle local.

    Le préfixe distingue les deux chemins, le suffixe `@N` demande le vecteur
    raccourci. Sans lui, la comparaison confondrait deux causes : un candidat à
    3 072 dimensions qui bat les 512 de jina gagne peut-être uniquement parce
    qu'il en a six fois plus, sur un corpus de 502 exemples.
    """
    if not modele.startswith("openai/"):
        return None
    nom, _, dims = modele.removeprefix("openai/").partition("@")
    return nom, int(dims) if dims else None


def cout_encodeurs(modeles: tuple[str, ...], textes: list[str]) -> float:
    """La dépense en dollars qu'engagerait la comparaison, avant de la lancer.

    Un caractère vaut environ un quart de token en anglais. L'estimation vise
    l'ordre de grandeur : assez pour décider, jamais présentée comme une
    facture.
    """
    tokens = sum(min(len(t), MAX_CHARS) for t in textes) / 4.0
    total = 0.0
    for modele in modeles:
        api = _encodeur_api(modele)
        if api is not None:
            total += tokens / 1_000_000 * TARIF_EMBEDDING.get(api[0], 0.13)
    return total


async def _notes_du_bareme(
    conn: Any, rubric_version: str
) -> tuple[dict[int, dict[str, float]], dict[int, tuple[int, str]]]:
    """Les notes courantes du barème, par ŒUVRE — jamais par identifiant TMDB.

    La nuance est devenue une nécessité avec les films : les deux catalogues
    TMDB se chevauchent, et agréger par `id_tmdb` fusionnerait le film 550 et
    la série 550 en une seule « œuvre » dont les notes se mélangeraient — sans
    erreur, sans avertissement, juste des poids entraînés sur des paires
    dossier/note dépareillées.

    Rend aussi `{oeuvre_id: (id_tmdb, univers)}` : c'est ce qu'il faut pour
    reconstruire le BON dossier, celui du bon catalogue.

    Partagée entre l'entraînement, les comparaisons et les diagnostics : cinq
    copies de cette requête ont existé, et c'est la cinquième qui a gardé le
    bug quand les quatre autres étaient corrigées.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select distinct on (s.oeuvre_id, s.axe)
                   s.oeuvre_id, o.id_tmdb, o.univers, s.axe, s.valeur
            from notation.score s
            join sourcing.oeuvre o on o.id = s.oeuvre_id
            where s.rubric_version = %s and s.modele <> %s and s.modele not like 'claude%%'
              and s.valeur is not null
            order by s.oeuvre_id, s.axe, s.scored_at desc
            """,
            (rubric_version, INTERNAL_MODEL),
        )
        rows = await cur.fetchall()

    by_work: dict[int, dict[str, float]] = {}
    infos: dict[int, tuple[int, str]] = {}
    for row in rows:
        by_work.setdefault(row["oeuvre_id"], {})[row["axe"]] = float(row["valeur"])
        infos[row["oeuvre_id"]] = (row["id_tmdb"], row["univers"])
    if len(by_work) < MIN_TRAINING_WORKS:
        raise PasAssezDOeuvres(len(by_work))
    return by_work, infos


async def _notes_et_dossiers(
    conn: Any, rubric: dict[str, Any]
) -> tuple[dict[int, dict[str, float]], dict[int, dict[str, Any]]]:
    """Les notes du juge et les dossiers assemblés, pour un barème.

    Partagé entre l'aperçu et la comparaison : le second doit chiffrer
    exactement ce que la première annonce, et deux requêtes écrites deux fois
    finissent toujours par diverger.

    Rend le dossier entier et non son seul texte : le `sha256` sert de clé de
    cache aux vecteurs payants, et le recalculer ailleurs serait la meilleure
    façon de payer deux fois le même encodage.
    """
    by_work, infos = await _notes_du_bareme(conn, rubric["version"])

    # Les dossiers, assemblés une seule fois : c'est la partie lente, et elle
    # ne dépend pas de l'encodeur qu'on évalue.
    dossiers: dict[int, dict[str, Any]] = {}
    for oeuvre_id, (id_tmdb, univers) in infos.items():
        built = await build_dossier(conn, id_tmdb, oeuvre_id=oeuvre_id, univers=univers)
        if built is not None:
            dossiers[oeuvre_id] = built
    return by_work, dossiers


async def _vecteurs_deja_payes(
    conn: Any, dossiers: dict[int, dict[str, Any]], etiquette: str
) -> dict[int, list[float]]:
    """Les vecteurs d'API déjà en cache pour ces dossiers exacts.

    Appariés sur `(id_tmdb, sha256)` : un dossier retouché depuis l'encodage
    n'a plus le même sha, sa ligne ne remonte pas, et il est réencodé. C'est la
    même règle que pour le modèle local, et c'est elle qui rend le cache sûr —
    sans quoi enrichir une œuvre laisserait son ancien vecteur en place.
    """
    # Apparié sur le pivot et non sur `id_tmdb` : les deux catalogues TMDB
    # numérotent séparément, et le film 550 comme la série 550 ont chacun leur
    # ligne dans `oeuvre` avec le même `id_tmdb`.
    par_oeuvre = {d["oeuvreId"]: i for i, d in dossiers.items() if d.get("oeuvreId") is not None}
    if not par_oeuvre:
        return {}
    shas = {d["oeuvreId"]: d["sha256"] for d in dossiers.values() if d.get("oeuvreId") is not None}
    async with conn.cursor() as cur:
        await cur.execute(
            """
            select e.oeuvre_id, e.vector from notation.embedding e
            where e.embedder = %s
              and (e.oeuvre_id, e.input_sha256)
                  in (select * from unnest(%s::bigint[], %s::text[]))
            """,
            (etiquette, list(par_oeuvre), [shas[o] for o in par_oeuvre]),
        )
        return {par_oeuvre[row[0]]: row[1] for row in await cur.fetchall()}


async def apercu_encodeurs(
    conn: Any, rubric: dict[str, Any], modeles: tuple[str, ...]
) -> dict[str, Any]:
    """Ce que la comparaison couvrirait et coûterait, sans rien encoder.

    Les candidats locaux sont gratuits ; ceux d'API ne le sont pas. Voir le
    montant avant de le dépenser est la seule façon de relancer sereinement une
    comparaison qu'on veut faire varier.

    Le devis déduit ce qui est déjà en cache : relancer la même comparaison
    doit afficher zéro, faute de quoi on hésiterait à la relancer alors qu'elle
    est gratuite.
    """
    _, dossiers = await _notes_et_dossiers(conn, rubric)
    total = 0.0
    detail: list[dict[str, Any]] = []
    for modele in modeles:
        api = _encodeur_api(modele)
        if api is None:
            detail.append({"modele": modele, "aEncoder": len(dossiers), "cout": 0.0})
            continue
        cache = await _vecteurs_deja_payes(conn, dossiers, modele.removeprefix("openai/"))
        restants = {i: d for i, d in dossiers.items() if i not in cache}
        cout = cout_encodeurs((modele,), [d["text"] for d in restants.values()])
        total += cout
        detail.append({"modele": modele, "aEncoder": len(restants), "cout": round(cout, 2)})
    return {"oeuvres": len(dossiers), "cout": round(total, 2), "modeles": detail}


async def comparer_encodeurs(
    conn: Any, settings: Any, rubric: dict[str, Any], modeles: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Met des encodeurs en concurrence sur les notes déjà rendues.

    Le protocole est celui de l'entraînement, à ceci près qu'il ne stocke
    rien : mêmes œuvres, mêmes notes, même régression, seul l'encodeur change.
    On compare des erreurs de validation croisée — ce que chaque encodeur
    permettrait de prédire sur une œuvre jamais vue.

    Un candidat préfixé `openai/` passe par l'API et devient payant. C'est le
    seul moyen de trancher ce que les quatre candidats locaux ne peuvent pas :
    ils s'équivalent à 0,006 près parce qu'ils sont de la même famille, tous
    petits, tous entraînés pour la similarité sémantique — leur égalité dit
    qu'ils sont interchangeables entre eux, pas qu'un encodeur plus savant ne
    ferait pas mieux.

    Aucun poids n'est écrit. Les vecteurs d'API, si : ils sont rangés dans
    `notation.embedding` sous leur propre étiquette d'encodeur.

    C'est un revirement, et il se justifie en deux points. La crainte d'origine
    — mêler des espaces vectoriels incompatibles dans la table de production —
    ne tient pas : `embedder` fait partie de la clé primaire, et le seul
    lecteur, `_embedding`, filtre dessus. Rien ne peut confondre un vecteur de
    jina avec un vecteur d'API.

    Et il y a une raison de les garder. Un vecteur d'API payé puis jeté se
    repaie à chaque relance ; surtout, ces vecteurs sont la matière d'une
    **distillation** — apprendre au petit modèle local à reproduire la
    représentation du gros. Cette piste-là ne demande aucune note du juge, donc
    aucune des 502 étiquettes qui bornent tout le reste : elle s'entraîne sur
    autant de dossiers qu'on veut en encoder. Jeter les vecteurs fermerait la
    porte avant de l'avoir essayée.
    """
    axes: list[str] = rubric["axes"]
    by_work, dossiers = await _notes_et_dossiers(conn, rubric)

    ids = [i for i in by_work if i in dossiers]
    resultats: list[dict[str, Any]] = []
    for rang, modele in enumerate(modeles, start=1):
        # Le journal tient lieu de barre de progression : chaque encodage dure
        # des minutes, et un silence de ce calibre ne se distingue pas d'un
        # blocage — on l'a pris pour tel en production.
        log.info(
            "encodeur %d/%d : %s — %d dossiers à encoder", rang, len(modeles), modele, len(ids)
        )
        api = _encodeur_api(modele)
        if api is None:
            vecteurs = await asyncio.to_thread(
                embed_texts,
                [dossiers[i]["text"] for i in ids],
                cache_dir=settings.embed_cache_dir,
                model=modele,
            )
            # Chaque candidat évalué est aussitôt déchargé : sans ça, les
            # arènes ONNX des quatre modèles s'empilent en mémoire résidente.
            liberer_modeles()
        else:
            nom, dims = api
            etiquette = modele.removeprefix("openai/")
            connus = await _vecteurs_deja_payes(conn, dossiers, etiquette)
            manquants = [i for i in ids if i not in connus]
            if manquants:
                if not settings.openai_api_key:
                    raise LlmError(f"{modele} demande OPENAI_API_KEY, absente du .env")
                log.info(
                    "encodeur %s : %d en cache, %d à payer",
                    modele,
                    len(ids) - len(manquants),
                    len(manquants),
                )
                # La même troncature que le chemin local, appliquée ici à la
                # main. Sans elle la comparaison mesurerait deux choses en même
                # temps — l'encodeur ET la quantité de texte lue — et un
                # candidat d'API gagnerait sans qu'on sache par quoi.
                async with httpx.AsyncClient() as http:
                    frais = await embed_openai(
                        http,
                        api_key=settings.openai_api_key,
                        model=nom,
                        textes=[dossiers[i]["text"][:MAX_CHARS] for i in manquants],
                        dimensions=dims,
                    )
                async with conn.cursor() as cur:
                    await cur.executemany(
                        """
                        insert into notation.embedding
                            (oeuvre_id, input_sha256, embedder, vector)
                        values (%s, %s, %s, %s) on conflict do nothing
                        """,
                        [
                            (dossiers[i]["oeuvreId"], dossiers[i]["sha256"], etiquette, Jsonb(v))
                            for i, v in zip(manquants, frais, strict=True)
                        ],
                    )
                connus.update(zip(manquants, frais, strict=True))
            vecteurs = [connus[i] for i in ids]
        log.info(
            "encodeur %d/%d : %s — encodage terminé, régression en cours",
            rang,
            len(modeles),
            modele,
        )
        par_oeuvre = dict(zip(ids, vecteurs, strict=True))

        par_axe: list[dict[str, Any]] = []
        for axe in axes:
            paires = [(par_oeuvre[i], by_work[i][axe]) for i in ids if axe in by_work[i]]
            if len(paires) < MIN_TRAINING_WORKS:
                continue
            poids = train_axis(axe, [p[0] for p in paires], [p[1] for p in paires])
            par_axe.append({"axe": axe, "maeCv": poids.mae_cv, "lambda": poids.lam})
        moyenne = sum(a["maeCv"] for a in par_axe) / len(par_axe) if par_axe else None
        resultats.append(
            {"modele": modele, "dims": len(vecteurs[0]), "moyenne": moyenne, "axes": par_axe}
        )
    return sorted(resultats, key=lambda r: r["moyenne"] if r["moyenne"] is not None else 9)


async def comparer_visuels(conn: Any, settings: Any, rubric: dict[str, Any]) -> dict[str, Any]:
    """Chiffre ce que les légendes visuelles apportent, et ce que leur absence coûte.

    Les mêmes œuvres, les mêmes notes, deux dossiers qui ne diffèrent que par
    la section MEDIA : tout écart mesuré vient donc des visuels et de rien
    d'autre. C'est la seule façon de répondre à « faut-il légender la traîne ? »
    autrement que par conviction — et la réponse engage plusieurs centaines
    d'euros à l'échelle du catalogue.

    N'écrit rien : ni vecteurs, ni poids. Les embeddings « sans médias » ne
    doivent surtout pas entrer dans `notation.embedding`, qui sert la
    production et n'a qu'une clé par œuvre et par empreinte.
    """
    axes: list[str] = rubric["axes"]
    by_work, infos = await _notes_du_bareme(conn, rubric["version"])

    avec: dict[int, str] = {}
    sans: dict[int, str] = {}
    legendees = 0
    for oeuvre_id, (id_tmdb, univers) in infos.items():
        a = await build_dossier(conn, id_tmdb, oeuvre_id=oeuvre_id, univers=univers)
        b = await build_dossier(conn, id_tmdb, oeuvre_id=oeuvre_id, univers=univers, medias=False)
        if a is None or b is None:
            continue
        avec[oeuvre_id], sans[oeuvre_id] = a["text"], b["text"]
        if a["sections"]["mediaLines"] > 0:
            legendees += 1

    ids = list(avec)
    log.info("diagnostic visuels : %d œuvres, dont %d légendées", len(ids), legendees)
    v_avec = await asyncio.to_thread(
        embed_texts, [avec[i] for i in ids], cache_dir=settings.embed_cache_dir
    )
    v_sans = await asyncio.to_thread(
        embed_texts, [sans[i] for i in ids], cache_dir=settings.embed_cache_dir
    )
    index = {i: n for n, i in enumerate(ids)}

    par_axe = []
    for axe in axes:
        retenus = [i for i in ids if axe in by_work[i]]
        if len(retenus) < MIN_TRAINING_WORKS:
            continue
        d = diagnostic_visuels(
            [v_avec[index[i]] for i in retenus],
            [v_sans[index[i]] for i in retenus],
            [by_work[i][axe] for i in retenus],
        )
        par_axe.append({"axe": axe, "notees": len(retenus), **d})
    return {"oeuvres": len(ids), "legendees": legendees, "axes": par_axe}


class PasAssezDOeuvres(RuntimeError):
    """Moins d'œuvres notées que le minimum : entraîner n'aurait pas de sens."""

    def __init__(self, works: int) -> None:
        super().__init__(
            f"{works} œuvre(s) notée(s) sur ce barème — il en faut au moins "
            f"{MIN_TRAINING_WORKS}. La phase 1 nourrit la phase 2."
        )
        self.works = works


async def entrainer_poids(conn: Any, settings: Any, rubric: dict[str, Any]) -> dict[str, Any]:
    """Réentraîne la régression sur TOUTES les notes OpenAI du barème.

    Toujours sur l'historique complet, jamais sur le dernier lot seul : les
    poids capitalisent, ils ne suivent pas la mode du dernier échantillon.

    Partagée entre le bouton de l'atelier et `fiv-admin training poids` : deux
    entrées qui entraîneraient différemment produiraient des poids
    incomparables sans que rien ne le signale.
    """
    axes: list[str] = rubric["axes"]
    rubric_version: str = rubric["version"]

    # La note courante de chaque œuvre : la plus récente par (œuvre, axe),
    # modèle OpenAI seulement — le contre-juge n'entraîne pas.
    by_work, infos = await _notes_du_bareme(conn, rubric_version)

    # Les embeddings de chaque œuvre notée, dossier reconstruit à l'identique.
    # Les dossiers sont gardés : la régénération plus bas en a besoin, et les
    # reconstruire une seconde fois doublait le nombre de requêtes — quatre
    # par œuvre, dont deux qui ramènent des payloads volumineux.
    vectors: dict[int, list[float]] = {}
    dossiers: dict[int, dict[str, Any]] = {}
    ecartees: list[int] = []
    # L'étiquette de production, et rien d'autre. Une œuvre dont l'encodeur a
    # dû passer par le secours local rend un vecteur d'un autre espace : le
    # mêler aux autres ne lèverait aucune erreur, il rendrait des poids qui ne
    # veulent rien dire. On l'écarte, elle reviendra au prochain entraînement.
    label_production = etiquette(settings.embedder)
    degradees: list[int] = []
    for oeuvre_id, (id_tmdb, univers) in infos.items():
        built = await build_dossier(conn, id_tmdb, oeuvre_id=oeuvre_id, univers=univers)
        if built is None:
            continue
        vecteur, label = await encoder_dossier(conn, settings, built)
        if label != label_production:
            degradees.append(oeuvre_id)
            continue
        dossiers[oeuvre_id] = built
        vectors[oeuvre_id] = vecteur
    if degradees:
        log.warning(
            "%d œuvre(s) écartée(s) de l'entraînement : encodées par le secours, pas par %s",
            len(degradees),
            label_production,
        )
    # Tout écarter et rendre « zéro axe entraîné » serait un succès apparent.
    # L'entraînement dirait qu'il a fini, les poids d'hier resteraient en
    # place, et rien n'indiquerait que l'encodeur n'a jamais répondu.
    if not vectors and degradees:
        raise EncodeurIndisponible(label_production, len(degradees))

    trained: list[dict[str, Any]] = []
    weights_json: dict[str, Any] = {}
    async with conn.cursor() as cur:
        for axe in axes:
            pairs = [
                (vectors[id_tmdb], scores[axe])
                for id_tmdb, scores in by_work.items()
                if axe in scores and id_tmdb in vectors
            ]
            if len(pairs) < MIN_TRAINING_WORKS:
                trained.append({"axe": axe, "trainedOn": len(pairs), "skipped": True})
                continue
            result = train_axis(axe, [p[0] for p in pairs], [p[1] for p in pairs])
            await cur.execute(
                """
                insert into notation.weights
                    (rubric_version, axe, intercept, coef, embedder, trained_on, mae_fit)
                values (%s, %s, %s, %s, %s, %s, %s)
                on conflict (rubric_version, axe) do update set
                    intercept = excluded.intercept,
                    coef = excluded.coef,
                    embedder = excluded.embedder,
                    trained_on = excluded.trained_on,
                    mae_fit = excluded.mae_fit,
                    trained_at = now()
                """,
                (
                    rubric_version,
                    axe,
                    result.intercept,
                    Jsonb(result.coef),
                    label_production,
                    result.trained_on,
                    result.mae_fit,
                ),
            )
            trained.append(
                {
                    "axe": axe,
                    "trainedOn": result.trained_on,
                    "maeFit": result.mae_fit,
                    "maeCv": result.mae_cv,
                    "lambda": result.lam,
                    "pente": result.pente,
                }
            )
            weights_json[axe] = {
                "intercept": result.intercept,
                "coef": result.coef,
                "trainedOn": result.trained_on,
                "maeFit": result.mae_fit,
                "maeCv": result.mae_cv,
                "lambda": result.lam,
                "pente": result.pente,
            }

        # Le journal des poids : tous les axes dans une ligne, datée — c'est
        # la version. Une ligne par prompt : réentraîner le même prompt la
        # redate et la remet en tête, donc en version par défaut.
        weights_id = None
        trained_at = None
        if weights_json:
            await cur.execute(
                """
                insert into notation.training_weights
                    (rubric_version, prompt, prompt_sha256, embedder, weights, works)
                values (%s, %s, %s, %s, %s, %s)
                on conflict (prompt_sha256) do update set
                    rubric_version = excluded.rubric_version,
                    embedder = excluded.embedder,
                    weights = excluded.weights,
                    works = excluded.works,
                    trained_at = now()
                returning id, trained_at
                """,
                (
                    rubric_version,
                    rubric["prompt"],
                    _prompt_sha(rubric["prompt"]),
                    label_production,
                    Jsonb(weights_json),
                    len(by_work),
                ),
            )
            weights_id, trained_at = await cur.fetchone()

    # Des poids neufs périment toutes les prédictions faites avec les anciens :
    # on régénère dans la foulée, pour chaque œuvre dont le journal porte un
    # verdict OpenAI. C'est gratuit — les embeddings viennent d'être calculés
    # ci-dessus, et le cache de `notation.embedding` couvre le reste.
    generated = 0
    if weights_json:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                select distinct on (t.oeuvre_id) t.oeuvre_id, o.id_tmdb, o.univers, t.prompt
                from notation.training_run t
                join sourcing.oeuvre o on o.id = t.oeuvre_id
                where t.rubric_version = %s and t.openai is not null
                order by t.oeuvre_id, t.created_at desc
                """,
                (rubric_version,),
            )
            journaux = await cur.fetchall()

        for entry in journaux:
            oeuvre_id = entry["oeuvre_id"]
            # Le dossier vient du tour précédent quand l'œuvre y était : c'est
            # le cas de la quasi-totalité d'entre elles, puisqu'on régénère
            # justement celles qui ont servi à entraîner.
            built = dossiers.get(oeuvre_id) or await build_dossier(
                conn, entry["id_tmdb"], oeuvre_id=oeuvre_id, univers=entry["univers"]
            )
            if built is None:
                continue
            vector = vectors.get(oeuvre_id) or await _embedding(conn, settings, built)
            await _store_internal(
                conn,
                oeuvre_id=entry["oeuvre_id"],
                internal=_predict_all(vector, weights_json),
                rubric_version=rubric_version,
                prompt=entry["prompt"],
                dossier_sha256=built["sha256"],
                raw_source_id=built["rawSourceId"],
            )
            generated += 1

    return {
        "rubricVersion": rubric_version,
        "works": len(by_work),
        "axes": trained,
        "weightsId": weights_id,
        "trainedAt": trained_at,
        "generated": generated,
        "skipped": ecartees,
    }


@router.post("/training/weights/train")
async def train_weights(
    user: CurrentUser, conn: Conn, settings: Config, body: TrainIn
) -> dict[str, Any]:
    """L'entraînement depuis l'atelier — même chemin que la ligne de commande."""
    if not settings.openai_api_key:
        raise HTTPException(status.HTTP_409_CONFLICT, "OPENAI_API_KEY absente du .env admin.")
    rubric = await _rubric(conn, body.rubricVersion)
    try:
        return await entrainer_poids(conn, settings, rubric)
    except PasAssezDOeuvres as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except EncodeurIndisponible as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except LlmError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


class Phase2In(BaseModel):
    id: int
    rubricVersion: str
    # L'univers de l'œuvre. Un identifiant TMDB seul ne désigne rien : les
    # deux catalogues se chevauchent, et 550 est un film comme une série.
    media: str = DEFAULT_MEDIA
    # Noter aussi avec OpenAI dans la foulée : c'est la « vérification avec le
    # LLM » de la boucle — comparer l'interne à une note fraîche, pas à une
    # note d'il y a trois barèmes.
    runLlm: bool = False


@router.post("/training/phase2")
async def phase2(user: CurrentUser, conn: Conn, settings: Config, body: Phase2In) -> dict[str, Any]:
    """La prédiction interne face aux notes LLM, œuvre par œuvre."""
    if not settings.openai_api_key:
        raise HTTPException(status.HTTP_409_CONFLICT, "OPENAI_API_KEY absente du .env admin.")
    rubric = await _rubric(conn, body.rubricVersion)
    axes: list[str] = rubric["axes"]

    # La version par défaut des poids : la ligne la plus récente du journal
    # pour ce barème ET cet encodeur. Chaque prompt a la sienne ; réentraîner
    # redate et remet en tête.
    #
    # L'encodeur entre dans la sélection parce que ses coefficients sont
    # dimensionnés sur lui : prédire un vecteur de 384 nombres avec des poids
    # appris sur 256 ne lèverait pas une erreur claire, ça produirait un
    # résultat faux ou un plantage obscur. Changer d'encodeur rend donc les
    # anciens poids invisibles — il faut réentraîner, et c'est bien ce qu'on
    # veut.
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select id, weights, works, trained_at from notation.training_weights
            where rubric_version = %s and embedder = %s
            order by trained_at desc limit 1
            """,
            (body.rubricVersion, etiquette(settings.embedder)),
        )
        weights_row = await cur.fetchone()
    if weights_row is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "aucun poids entraîné pour ce barème — lancer d'abord l'entraînement "
            "(il faut au moins 10 œuvres notées en phase 1).",
        )
    weight_rows: dict[str, dict[str, Any]] = weights_row["weights"]

    univers = _univers(body.media)
    oeuvre_id = await pivot(conn, body.id, univers=univers)
    built = await build_dossier(conn, body.id, oeuvre_id=oeuvre_id, univers=univers)
    if built is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"œuvre {body.id} non collectée")

    async with httpx.AsyncClient() as http:
        try:
            vector, label = await encoder_dossier(conn, settings, built)
            # Le secours local vit dans un autre espace que les poids. Prédire
            # quand même rendrait six nombres plausibles et faux, ce qui est
            # pire qu'une erreur : on ne saurait pas qu'il faut la refaire.
            if label != etiquette(settings.embedder):
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    f"encodeur {settings.embedder} indisponible — vecteur produit par"
                    f" {label}, incompatible avec les poids. Réessayer plus tard.",
                )
            llm_result: dict[str, Any] | None = None
            if body.runLlm:
                llm_result = await score_openai(
                    http,
                    api_key=settings.openai_api_key,
                    model=settings.openai_model,
                    prompt=rubric["prompt"],
                    dossier=built["text"],
                    axes=axes,
                )
        except LlmError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    internal = _predict_all(vector, weight_rows)

    if llm_result is not None:
        await _store_scores(
            conn,
            oeuvre_id=oeuvre_id,
            scores=llm_result["scores"],
            rubric_version=body.rubricVersion,
            modele=llm_result["model"],
            input_sha256=built["sha256"],
            prompt_sha256=_prompt_sha(rubric["prompt"]),
        )
        llm_scores = llm_result["scores"]
        llm_origin = {"model": llm_result["model"], "fresh": True}
    else:
        # À défaut d'une note fraîche : la dernière note OpenAI stockée.
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                select distinct on (axe) axe, valeur, confiance, modele, scored_at
                from notation.score
                where oeuvre_id = %s and rubric_version = %s
                  and modele <> %s and modele not like 'claude%%'
                order by axe, scored_at desc
                """,
                (oeuvre_id, body.rubricVersion, INTERNAL_MODEL),
            )
            stored = await cur.fetchall()
        llm_scores = {
            row["axe"]: {
                "score": float(row["valeur"]) if row["valeur"] is not None else None,
                "confidence": float(row["confiance"]) if row["confiance"] is not None else None,
            }
            for row in stored
        }
        llm_origin = (
            {"model": stored[0]["modele"], "fresh": False, "scoredAt": stored[0]["scored_at"]}
            if stored
            else None
        )

    # Le contre-juge, s'il s'est prononcé sur ce barème. La phase 2 le montre
    # à côté d'OpenAI : deux lignées face à la régression, c'est ce qui permet
    # de voir si l'interne dérive vers l'une d'elles.
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select distinct on (axe) axe, valeur, confiance, modele, scored_at
            from notation.score
            where oeuvre_id = %s and rubric_version = %s and modele like 'claude%%'
            order by axe, scored_at desc
            """,
            (oeuvre_id, body.rubricVersion),
        )
        contre = await cur.fetchall()
    claude_scores = {
        row["axe"]: {
            "score": float(row["valeur"]) if row["valeur"] is not None else None,
            "confidence": float(row["confiance"]) if row["confiance"] is not None else None,
        }
        for row in contre
    }
    claude_origin = (
        {"model": contre[0]["modele"], "scoredAt": contre[0]["scored_at"]} if contre else None
    )

    internal_scores = {axe: {"score": entry["score"]} for axe, entry in internal.items()}

    run_id = await _store_internal(
        conn,
        oeuvre_id=oeuvre_id,
        internal=internal,
        rubric_version=body.rubricVersion,
        prompt=rubric["prompt"],
        dossier_sha256=built["sha256"],
        raw_source_id=built["rawSourceId"],
    )

    return {
        "id": body.id,
        "runId": run_id,
        "dossier": {key: built[key] for key in ("sha256", "chars", "title")},
        "weights": {
            "id": weights_row["id"],
            "trainedAt": weights_row["trained_at"],
            "works": weights_row["works"],
        },
        "internal": internal,
        "llm": {"scores": llm_scores, "origin": llm_origin},
        "claude": {"scores": claude_scores, "origin": claude_origin},
        "gaps": _gaps(internal_scores, llm_scores, axes) if llm_scores else None,
    }


async def comparer_modeles(conn: Any, settings: Any, rubric: dict[str, Any]) -> dict[str, Any]:
    """Ridge contre plus proches voisins, sur les mêmes œuvres et les mêmes plis.

    La question ouverte depuis le début, et jamais posée : le plafond vient-il
    de la matière, ou de la **forme** du modèle ? On a éliminé le volume (deux
    plateaux mesurés), l'encodeur (trois candidats à 0,006 près) et la
    calibration (l'amplitude est restituée à 93-103 %). Reste que la régression
    est **linéaire**, et qu'un espace d'embeddings ne l'est pas.

    Le cas qui l'a rendu visible : Lucifer, notée 6 en joie par le juge et 3,1
    par la ridge. Le modèle la classe 98ᵉ sur 502 quand le juge la met 290ᵉ —
    ce n'est pas une erreur d'échelle mais de rang, et aucune calibration de
    sortie ne la corrige. « Drôle malgré une intrigue de policier surnaturel »
    n'est probablement pas une projection linéaire ; c'est en revanche
    exactement ce que dit un voisinage, si les voisins sont les bons.

    N'écrit rien : ni poids, ni vecteurs. C'est une mesure, pas un
    entraînement, et elle ne coûte aucun appel payant — les embeddings sont
    déjà en cache.
    """
    axes: list[str] = rubric["axes"]
    by_work, infos = await _notes_du_bareme(conn, rubric["version"])

    vectors: dict[int, list[float]] = {}
    for oeuvre_id, (id_tmdb, univers) in infos.items():
        built = await build_dossier(conn, id_tmdb, oeuvre_id=oeuvre_id, univers=univers)
        if built is not None:
            vectors[oeuvre_id] = await _embedding(conn, settings, built)

    resultats = []
    for axe in axes:
        paires = [
            (vectors[i], scores[axe])
            for i, scores in by_work.items()
            if axe in scores and i in vectors
        ]
        if len(paires) < MIN_TRAINING_WORKS:
            continue
        resultats.append(comparer_modeles_axe(axe, [p[0] for p in paires], [p[1] for p in paires]))

    return {"rubricVersion": rubric["version"], "oeuvres": len(vectors), "axes": resultats}


# Le titre exact de la section Wikipédia dans le dossier assemblé. Sert à
# retrouver sa position pour savoir ce que la troncature de l'encodeur en
# laisse : `dossier.py` la place tôt depuis le cas Docteur House, mais « tôt »
# n'est pas « toujours dans les douze mille premiers caractères ».
MARQUE_WIKIPEDIA = "WIKIPEDIA (en):\n"


async def diagnostic_matiere(
    conn: Any, settings: Any, rubric: dict[str, Any], *, focus: int | None = None
) -> dict[str, Any]:
    """Ce que l'encodeur ne lit pas du dossier, et si ça se voit sur l'erreur.

    Le juge et l'encodeur ne reçoivent pas le même texte. GPT lit le dossier
    entier ; `embed_texts` le tronque à `MAX_CHARS`. Pour toute fiche qui
    dépasse, la cible `y` est donc fonction d'un texte que le vecteur `x` n'a
    jamais vu — et aucune régression ne rattrape une asymétrie d'entrée.

    Trois mesures, toutes gratuites :

    * combien de dossiers dépassent la coupe, et de combien ;
    * si l'erreur hors-pli monte avec la longueur. Une erreur plate innocente
      la troncature et renvoie chercher ailleurs ; une erreur croissante la
      condamne, et relever `MAX_CHARS` devient le levier ;
    * le voisinage cosine d'une œuvre, quand `focus` est donné. C'est la
      question posée avant toute autre : si l'encodeur range Lucifer près des
      policiers surnaturels, ni la ridge, ni le noyau, ni un réseau ne la
      remettront près des comédies. On ne choisit pas un modèle avant d'avoir
      regardé ce que la représentation contient.

    N'écrit rien et n'appelle aucune API payante : les vecteurs sont en cache.
    """
    axes: list[str] = rubric["axes"]
    by_work, infos = await _notes_du_bareme(conn, rubric["version"])

    # `focus` arrive en identifiant TMDB — c'est ce que l'utilisateur connaît —
    # mais tout ici est indexé par œuvre. Série d'abord en cas de chevauchement.
    focus_oeuvre = None
    if focus is not None:
        candidats = sorted(
            (o for o, (i, _) in infos.items() if i == focus),
            key=lambda o: infos[o][1] != "series",
        )
        focus_oeuvre = candidats[0] if candidats else None

    dossiers: dict[int, dict[str, Any]] = {}
    vectors: dict[int, list[float]] = {}
    for oeuvre_id, (id_tmdb, univers) in infos.items():
        built = await build_dossier(conn, id_tmdb, oeuvre_id=oeuvre_id, univers=univers)
        if built is not None:
            dossiers[oeuvre_id] = built
            vectors[oeuvre_id] = await _embedding(conn, settings, built)

    # L'erreur hors-pli, moyennée sur les axes que le juge a bien voulu noter.
    # Une œuvre qu'il a laissée en null sur deux axes compte sur les quatre
    # autres : l'exclure biaiserait vers les dossiers riches, qui sont
    # justement ceux qu'on soupçonne d'être coupés.
    erreurs: dict[int, list[float]] = {}
    predit_focus: dict[str, float] = {}
    for axe in axes:
        ids = [i for i, s in by_work.items() if axe in s and i in vectors]
        if len(ids) < MIN_TRAINING_WORKS:
            continue
        vs = [vectors[i] for i in ids]
        ys = [by_work[i][axe] for i in ids]
        preds = predictions_ridge(vs, ys, train_axis(axe, vs, ys))
        for id_tmdb, brut, juge in zip(ids, preds, ys, strict=True):
            valeur = float(brut)
            if math.isnan(valeur):
                continue
            erreurs.setdefault(id_tmdb, []).append(abs(valeur - juge))
            if id_tmdb == focus_oeuvre:
                predit_focus[axe] = round(valeur, 1)

    fiches: list[dict[str, Any]] = []
    for id_tmdb, built in dossiers.items():
        texte: str = built["text"]
        wiki = int(built["sections"]["wikipediaChars"])
        debut = texte.find(MARQUE_WIKIPEDIA)
        # Ce qui reste de l'article une fois la coupe passée : zéro si la
        # section commence déjà après la borne, entier si elle finit avant.
        vus = (
            0
            if not wiki or debut < 0
            else max(0, min(MAX_CHARS - (debut + len(MARQUE_WIKIPEDIA)), wiki))
        )
        mesures = erreurs.get(id_tmdb, [])
        fiches.append(
            {
                "idTmdb": infos[id_tmdb][0],
                "titre": built["title"],
                "chars": len(texte),
                "coupe": max(0, len(texte) - MAX_CHARS),
                "wikipediaChars": wiki,
                "wikipediaVus": vus,
                "erreur": round(sum(mesures) / len(mesures), 3) if mesures else None,
            }
        )
    fiches.sort(key=lambda f: int(f["chars"]))

    total = sum(int(f["chars"]) for f in fiches)
    coupe = sum(int(f["coupe"]) for f in fiches)
    avec_wiki = [f for f in fiches if int(f["wikipediaChars"]) > 0]
    tranches = [
        ("moins de 6 000", 0, 6_000),
        ("6 000 – 12 000", 6_000, MAX_CHARS),
        ("12 000 – 20 000", MAX_CHARS, 20_000),
        ("plus de 20 000", 20_000, 10**9),
    ]

    notees = [f for f in fiches if f["erreur"] is not None]
    quartiles: list[dict[str, Any]] = []
    if len(notees) >= 8:
        taille = len(notees) // 4
        for q in range(4):
            debut_q = q * taille
            fin_q = len(notees) if q == 3 else (q + 1) * taille
            lot = notees[debut_q:fin_q]
            quartiles.append(
                {
                    "rang": q + 1,
                    "oeuvres": len(lot),
                    "charsMin": int(lot[0]["chars"]),
                    "charsMax": int(lot[-1]["chars"]),
                    "mae": round(sum(float(f["erreur"]) for f in lot) / len(lot), 3),
                }
            )

    correlation = None
    if len(notees) >= 3:
        longueurs = [float(f["chars"]) for f in notees]
        valeurs = [float(f["erreur"]) for f in notees]
        ml = sum(longueurs) / len(longueurs)
        mv = sum(valeurs) / len(valeurs)
        cov = sum((a - ml) * (b - mv) for a, b in zip(longueurs, valeurs, strict=True))
        el = math.sqrt(sum((a - ml) ** 2 for a in longueurs))
        ev = math.sqrt(sum((b - mv) ** 2 for b in valeurs))
        if el > 1e-9 and ev > 1e-9:
            correlation = round(cov / (el * ev), 2)

    voisinage: dict[str, Any] | None = None
    if focus_oeuvre is not None and focus_oeuvre in vectors:
        ordre = list(vectors)
        matrice = [vectors[i] for i in ordre]
        juges = by_work.get(focus_oeuvre, {})
        pire = max(
            (a for a in axes if a in juges and a in predit_focus),
            key=lambda a: abs(juges[a] - predit_focus[a]),
            default=None,
        )
        voisinage = {
            "idTmdb": focus,
            "titre": dossiers[focus_oeuvre]["title"] if focus_oeuvre in dossiers else str(focus),
            "axePireEcart": pire,
            "juge": {a: juges.get(a) for a in axes},
            "modele": {a: predit_focus.get(a) for a in axes},
            "voisins": [
                {
                    "idTmdb": infos[ordre[i]][0],
                    "titre": dossiers[ordre[i]]["title"],
                    "cosinus": round(sim, 3),
                    "juge": by_work.get(ordre[i], {}).get(pire) if pire else None,
                }
                for i, sim in voisins_cosinus(matrice, ordre.index(focus_oeuvre), 10)
            ],
        }

    return {
        "rubricVersion": rubric["version"],
        "oeuvres": len(fiches),
        "coupe": MAX_CHARS,
        "tranches": [
            {
                "libelle": libelle,
                "oeuvres": sum(1 for f in fiches if bas <= int(f["chars"]) < haut),
            }
            for libelle, bas, haut in tranches
        ],
        "tronques": sum(1 for f in fiches if int(f["coupe"]) > 0),
        "partPerdue": round(coupe / total, 3) if total else 0.0,
        "wikipedia": {
            "presente": len(avec_wiki),
            "entiere": sum(
                1 for f in avec_wiki if int(f["wikipediaVus"]) >= int(f["wikipediaChars"])
            ),
            "coupee": sum(
                1 for f in avec_wiki if 0 < int(f["wikipediaVus"]) < int(f["wikipediaChars"])
            ),
            "absente": sum(1 for f in avec_wiki if int(f["wikipediaVus"]) == 0),
        },
        "quartiles": quartiles,
        "correlation": correlation,
        "voisinage": voisinage,
    }


CARTE_PAR_UNIVERS = {m.univers: f"admin.{m.card_view}" for m in MEDIA.values()}


async def constituer_corpus(
    conn: Any,
    settings: Any,
    modele: str,
    *,
    limit: int,
    univers: str = "series",
    apercu: bool = False,
    progres: Any = None,
) -> dict[str, Any]:
    """Encode les N œuvres les plus populaires avec un encodeur d'API, et range.

    C'est la constitution du corpus de distillation : des paires
    `dossier → vecteur du professeur`, sur lesquelles on apprendra plus tard au
    petit modèle local à reproduire la représentation du gros. La cible est un
    vecteur de 512 nombres et non six notes, donc chaque œuvre apporte 512
    signaux — c'est ce qui rend l'exercice possible sur quelques milliers
    d'œuvres là où il faudrait des millions d'étiquettes.

    **Le corpus n'a pas besoin d'être noté.** N'importe quel dossier fait
    l'affaire, y compris ceux de la traîne obscure — et c'est justement la
    traîne que l'élève devra savoir traiter. La limite des 502 œuvres jugées,
    qui borne tout le reste du projet, ne s'applique pas ici.

    L'écriture se fait lot par lot, pas à la fin. Cinq mille œuvres font une
    dizaine de minutes d'appels ; une interruption au huitième lot doit laisser
    les sept premiers en base, sinon on repaie tout. La connexion étant en
    `autocommit`, chaque lot est durable dès son insertion.

    Les œuvres déjà encodées sous cette étiquette, pour ce dossier exact, sont
    sautées : relancer la commande continue le corpus au lieu de le refaire.
    """
    api = _encodeur_api(modele)
    if api is None:
        raise LlmError(f"{modele} n'est pas un encodeur d'API — le corpus n'aurait rien à ranger")
    nom, dims = api
    etiquette = modele.removeprefix("openai/")

    carte = CARTE_PAR_UNIVERS.get(univers)
    if carte is None:
        raise LlmError(f"univers inconnu : {univers} — attendus {sorted(CARTE_PAR_UNIVERS)}")

    async with conn.cursor(row_factory=dict_row) as cur:
        # Le nom de la vue est interpolé, pas passé en paramètre : PostgreSQL
        # n'accepte pas de table paramétrée. Il ne vient jamais de l'extérieur —
        # `CARTE_PAR_UNIVERS` est une table close, et un univers absent a levé
        # deux lignes plus haut.
        await cur.execute(
            f"""
            select v.id as id_tmdb, coalesce(v.name, v.original_name) as titre
            from {carte} v
            join tmdb_catalog c on c.univers = %(univers)s and c.id = v.id
            order by c.popularity desc nulls last, v.vote_average desc nulls last
            limit %(limit)s
            """,  # noqa: S608
            {"univers": univers, "limit": limit},
        )
        candidates = list(await cur.fetchall())

    dossiers: dict[int, dict[str, Any]] = {}
    for row in candidates:
        built = await build_dossier(conn, row["id_tmdb"], univers=univers)
        # Un dossier vide n'apprend rien ; un dossier maigre, si — c'est même
        # exactement ce que l'élève devra savoir traiter sur la traîne.
        if built is not None and built["text"].strip():
            dossiers[row["id_tmdb"]] = built

    connus = await _vecteurs_deja_payes(conn, dossiers, etiquette)
    manquants = [i for i in dossiers if i not in connus]
    devis = round(cout_encodeurs((modele,), [dossiers[i]["text"] for i in manquants]), 2)
    if apercu or not manquants:
        return {
            "modele": modele,
            "univers": univers,
            "candidates": len(candidates),
            "dossiers": len(dossiers),
            "enCache": len(connus),
            "aEncoder": len(manquants),
            "cout": devis,
            "encodes": 0,
        }

    if not settings.openai_api_key:
        raise LlmError(f"{modele} demande OPENAI_API_KEY, absente du .env")

    faits = 0
    async with httpx.AsyncClient() as http:
        for depart in range(0, len(manquants), LOT_EMBEDDING):
            lot = manquants[depart : depart + LOT_EMBEDDING]
            vecteurs = await embed_openai(
                http,
                api_key=settings.openai_api_key,
                model=nom,
                # La même troncature que le chemin local : l'élève apprendra à
                # reproduire ce que le professeur voit, et il ne verra jamais
                # plus que ces douze mille caractères.
                textes=[dossiers[i]["text"][:MAX_CHARS] for i in lot],
                dimensions=dims,
            )
            # Par le pivot et non par `id_tmdb` : la table est passée à
            # `oeuvre_id` avec l'arrivée des films, et les deux catalogues TMDB
            # ont des numérotations séparées — le film 550 et la série 550 sont
            # deux œuvres. Écrire l'identifiant TMDB nu les confondrait.
            async with conn.cursor() as cur:
                await cur.executemany(
                    """
                    insert into notation.embedding (oeuvre_id, input_sha256, embedder, vector)
                    values (%s, %s, %s, %s) on conflict do nothing
                    """,
                    [
                        (dossiers[i]["oeuvreId"], dossiers[i]["sha256"], etiquette, Jsonb(v))
                        for i, v in zip(lot, vecteurs, strict=True)
                    ],
                )
            faits += len(lot)
            if progres is not None:
                progres(faits, len(manquants))

    return {
        "modele": modele,
        "univers": univers,
        "candidates": len(candidates),
        "dossiers": len(dossiers),
        "enCache": len(connus),
        "aEncoder": len(manquants),
        "cout": devis,
        "encodes": faits,
    }


async def exporter_corpus(
    conn: Any, etiquette_prof: str, sortie: Any, *, progres: Any = None
) -> dict[str, Any]:
    """Écrit les paires `dossier → vecteur du professeur` dans un JSONL.

    C'est l'entrée de la distillation, et elle se fait ici plutôt que dans le
    script d'entraînement pour une raison : le texte n'est pas stocké. Seul son
    sha l'est, à côté du vecteur. Le dossier doit donc être réassemblé par le
    code qui sait le faire — même sections, même ordre, même troncature — sinon
    l'élève apprendrait à associer un vecteur à un texte que le professeur n'a
    jamais lu.

    Le sha est revérifié pour chaque paire. Une œuvre enrichie depuis son
    encodage a changé de dossier : son vecteur ne lui correspond plus, et la
    paire est écartée plutôt que d'enseigner une correspondance fausse.

    Aucun appel payant : tout est déjà en base.
    """
    import json

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select o.id_tmdb, o.univers, e.input_sha256, e.vector
            from notation.embedding e
            join sourcing.oeuvre o on o.id = e.oeuvre_id
            where e.embedder = %s
            order by o.univers, o.id_tmdb
            """,
            (etiquette_prof,),
        )
        lignes = await cur.fetchall()

    ecrites = perimees = introuvables = 0
    for n, row in enumerate(lignes, start=1):
        built = await build_dossier(conn, row["id_tmdb"], univers=row["univers"])
        if built is None:
            introuvables += 1
            continue
        if built["sha256"] != row["input_sha256"]:
            perimees += 1
            continue
        sortie.write(
            json.dumps(
                {
                    "idTmdb": row["id_tmdb"],
                    "univers": row["univers"],
                    # Tronqué comme à l'encodage : l'élève doit voir exactement
                    # ce que le professeur a vu, sans quoi il apprend à prédire
                    # un vecteur depuis un texte plus long que l'original.
                    "text": built["text"][:MAX_CHARS],
                    "vector": row["vector"],
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        ecrites += 1
        if progres is not None and n % 500 == 0:
            progres(n, len(lignes))

    return {
        "professeur": etiquette_prof,
        "candidates": len(lignes),
        "ecrites": ecrites,
        "perimees": perimees,
        "introuvables": introuvables,
    }


# Les genres TMDB qu'on s'attend à voir peser sur chaque axe. La liste couvre
# les deux catalogues, qui ne nomment pas pareil : « Action & Adventure » côté
# série, « Action » et « Adventure » côté film.
#
# C'est un critère VOLONTAIREMENT imparfait, et c'est ce qui le rend
# informatif. Le barème interdit explicitement de recopier le genre — « Score
# the emotion the work delivers, never its genre label » — donc un axe qui
# collerait parfaitement au genre aurait échoué, et un axe sans aucun lien
# mesurerait quelque chose que personne ne reconnaîtrait. C'est l'entre-deux
# qu'on cherche : un écart net, pas un écart total.
GENRES_ATTENDUS = {
    "joie": {"Comedy"},
    "reve": {"Sci-Fi & Fantasy", "Fantasy", "Science Fiction", "Animation"},
    "tristesse": {"Drama"},
    "peur": {"Horror", "Thriller", "Mystery"},
    "reflexion": {"Documentary"},
    "action": {"Action & Adventure", "Action", "Adventure", "War & Politics", "War"},
}


def _ancres_du_bareme(prompt: str) -> dict[str, dict[str, float]]:
    """Les œuvres de référence déclarées par le barème, axe par axe.

    Elles vivent dans le texte du prompt (`Anchors: Chernobyl = 1, …`) parce
    que c'est le juge qui les lit. Les relire ici permet de poser au système la
    question la plus élémentaire qu'on ne lui avait jamais posée : **reproduit-il
    ses propres définitions ?**
    """
    import re

    resultat: dict[str, dict[str, float]] = {}
    axe_courant: str | None = None
    for ligne in prompt.splitlines():
        entete = re.match(r"\s*\d+\.\s+(\w+)\s+—", ligne)
        if entete:
            axe_courant = entete.group(1)
            continue
        declaration = re.match(r"\s*Anchors:\s*(.+)", ligne)
        if declaration and axe_courant:
            paires: dict[str, float] = {}
            for morceau in declaration.group(1).rstrip(".").split(","):
                if "=" not in morceau:
                    continue
                titre, valeur = morceau.rsplit("=", 1)
                with contextlib.suppress(ValueError):
                    paires[_normaliser(titre)] = float(valeur.strip())
            resultat[axe_courant] = paires
            axe_courant = None
    return resultat


def _normaliser(titre: str) -> str:
    """Un titre comparable : minuscules, sans ponctuation ni article initial."""
    import re

    net = re.sub(r"[^a-z0-9 ]+", "", titre.strip().lower())
    return re.sub(r"^(the|a|an|le|la|les|un|une) ", "", net).strip()


async def mesurer_validite(conn: Any, rubric: dict[str, Any]) -> dict[str, Any]:
    """La validité des notes, pas leur fidélité — la question jamais posée.

    Tout ce que le projet a mesuré jusqu'ici est de la **fidélité** : le juge
    d'accord avec lui-même (0,37), la régression d'accord avec le juge (0,84).
    Ça établit qu'un thermomètre rend toujours la même valeur, pas qu'elle soit
    la bonne. Un thermomètre déréglé de trois degrés est parfaitement fidèle.

    Trois angles, tous gratuits, tous imparfaits séparément :

    * **les ancres** — le barème déclare 24 œuvres de référence avec leur note.
      Le juge les reproduit-il ? C'est la validité interne : un système qui ne
      retrouve pas ses propres définitions ne mesure rien de défini ;
    * **les genres TMDB** — critère extérieur, produit par d'autres, sans
      rapport avec ce barème. Les œuvres d'action doivent scorer plus haut en
      `action` que les autres. Écart nul = l'axe ne mesure rien de
      reconnaissable ; écart total = il recopie le genre au lieu du ton, ce que
      le barème interdit ;
    * **le contre-juge** — Haiku, autre famille de modèle, sur le même dossier.
      Un accord entre deux lignées est le seul indice qu'on ne mesure pas la
      lubie d'un modèle.

    Aucun des trois ne prouve la validité. Un désaccord franc sur l'un des
    trois, en revanche, la réfute — et c'est ce qu'on cherche : de quoi savoir
    si « action 5,5 » est une mesure ou une décoration.
    """
    axes: list[str] = rubric["axes"]
    by_work, infos = await _notes_du_bareme(conn, rubric["version"])
    oeuvres = list(by_work)

    # --- 1. Les ancres -------------------------------------------------------
    ancres = _ancres_du_bareme(rubric["prompt"])
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            -- Deux titres par œuvre, et il en faut deux : les ancres du
            -- barème sont en anglais (« The Haunting of Hill House »), le
            -- pivot garde souvent le titre d'affichage francisé.
            select o.id as oeuvre_id, c.original_name, o.titre
            from sourcing.oeuvre o
            join sourcing.tmdb_catalog c on c.univers = o.univers and c.id = o.id_tmdb
            where o.id = any(%s)
            """,
            (oeuvres,),
        )
        titres = await cur.fetchall()
    par_titre: dict[str, int] = {}
    for row in titres:
        for brut in (row["original_name"], row["titre"]):
            if brut:
                par_titre.setdefault(_normaliser(brut), row["oeuvre_id"])

    bilan_ancres: list[dict[str, Any]] = []
    for axe in axes:
        ecarts: list[tuple[str, float, float]] = []
        for titre, attendu in ancres.get(axe, {}).items():
            oeuvre = par_titre.get(titre)
            rendu = by_work.get(oeuvre, {}).get(axe) if oeuvre else None
            if rendu is not None:
                ecarts.append((titre, attendu, rendu))
        bilan_ancres.append(
            {
                "axe": axe,
                "declarees": len(ancres.get(axe, {})),
                "trouvees": len(ecarts),
                "ecartMoyen": (
                    round(sum(abs(a - r) for _, a, r in ecarts) / len(ecarts), 2)
                    if ecarts
                    else None
                ),
                "pire": (
                    max(
                        ({"titre": t, "declare": a, "rendu": r} for t, a, r in ecarts),
                        key=lambda e: abs(float(e["declare"]) - float(e["rendu"])),
                    )
                    if ecarts
                    else None
                ),
            }
        )

    # --- 2. Le critère extérieur : les genres --------------------------------
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            with fiche as (
                select distinct on (o.id) o.id as oeuvre_id, r.payload
                from sourcing.oeuvre o
                join sourcing.raw_source r
                  on r.source = 'tmdb'
                 and r.source_id = o.id_tmdb::text
                 and r.kind = case o.univers when 'movies' then 'movie' else 'tv' end
                 and r.http_status between 200 and 299
                 and r.payload is not null
                where o.id = any(%s)
                order by o.id, r.fetched_at desc
            )
            select oeuvre_id, g ->> 'name' as genre
            from fiche, jsonb_array_elements(payload -> 'genres') g
            """,
            (oeuvres,),
        )
        lignes = await cur.fetchall()
    genres: dict[int, set[str]] = {}
    for row in lignes:
        if row["genre"]:
            genres.setdefault(row["oeuvre_id"], set()).add(row["genre"])

    bilan_genres: list[dict[str, Any]] = []
    for axe in axes:
        attendus = GENRES_ATTENDUS.get(axe, set())
        avec = [n[axe] for o, n in by_work.items() if axe in n and genres.get(o, set()) & attendus]
        sans = [
            n[axe]
            for o, n in by_work.items()
            if axe in n and o in genres and not (genres[o] & attendus)
        ]
        bilan_genres.append(
            {
                "axe": axe,
                "genres": sorted(attendus),
                "avec": len(avec),
                "moyenneAvec": round(sum(avec) / len(avec), 2) if avec else None,
                "moyenneSans": round(sum(sans) / len(sans), 2) if sans else None,
                "ecart": (
                    round(sum(avec) / len(avec) - sum(sans) / len(sans), 2)
                    if avec and sans
                    else None
                ),
            }
        )

    # --- 3. Le contre-juge ---------------------------------------------------
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select distinct on (t.oeuvre_id) t.oeuvre_id, t.claude
            from notation.training_run t
            where t.rubric_version = %s and t.claude is not null
            order by t.oeuvre_id, t.created_at desc
            """,
            (rubric["version"],),
        )
        contre = await cur.fetchall()

    ecarts_juges: dict[str, list[float]] = {axe: [] for axe in axes}
    for row in contre:
        verdicts = (row["claude"] or {}).get("scores") or row["claude"] or {}
        for axe in axes:
            entree = verdicts.get(axe)
            autre = entree.get("score") if isinstance(entree, dict) else entree
            propre = by_work.get(row["oeuvre_id"], {}).get(axe)
            if isinstance(autre, int | float) and propre is not None:
                ecarts_juges[axe].append(abs(float(autre) - propre))

    bilan_juges = [
        {
            "axe": axe,
            "oeuvres": len(valeurs),
            "ecartMoyen": round(sum(valeurs) / len(valeurs), 2) if valeurs else None,
        }
        for axe, valeurs in ecarts_juges.items()
    ]

    return {
        "rubricVersion": rubric["version"],
        "oeuvres": len(by_work),
        "ancres": bilan_ancres,
        "genres": bilan_genres,
        "contreJuge": bilan_juges,
        "contreJugeOeuvres": len(contre),
    }
