"""Le canal vidéo : extraire du brut TMDB les bandes-annonces et extraits.

Aucun appel réseau. TMDB sert déjà les vidéos dans `videos` — c'est dans
`SERIES_APPEND` et `SEASON_APPEND` depuis le premier jour — et cette passe ne
fait que projeter ce qui dort dans `raw_source.payload` vers une table
interrogeable. D'où sa rapidité, et d'où le fait qu'elle puisse être relancée
sans rien coûter d'autre que du temps machine.

Ce qu'elle n'est pas : un fournisseur de vidéos. TMDB ne connaît qu'une partie
des bandes-annonces, et presque jamais les doublages non anglophones. Compléter
par un autre fournisseur se fera en ajoutant des lignes de `source` différente
— la table est faite pour, la clé primaire portant l'hébergeur et non la
provenance.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fiv_sourcing import store

# TMDB déclare le site en toutes lettres. On garde tel quel plutôt que de
# normaliser : le jour où un troisième hébergeur apparaît, une valeur inconnue
# vaut mieux qu'une valeur écrasée.
SITES_LISIBLES = {"YouTube", "Vimeo"}


def _date(valeur: Any) -> datetime | None:
    """`published_at` arrive en ISO 8601 avec un Z final que `fromisoformat`
    n'acceptait pas avant 3.11 — et parfois vide, parfois absent."""
    if not isinstance(valeur, str) or not valeur:
        return None
    try:
        return datetime.fromisoformat(valeur.replace("Z", "+00:00"))
    except ValueError:
        return None


def extraire(payload: dict[str, Any] | None, *, saison: int | None = None) -> list[dict[str, Any]]:
    """Les vidéos d'une fiche, normalisées. Liste vide si la fiche n'en a pas.

    On ne filtre ni sur le type ni sur la langue : un « Featurette » ou une
    bande-annonce italienne ne servent pas la fiche française, mais les jeter
    ici obligerait à re-projeter tout le catalogue le jour où l'on en voudra.
    Le tri se fait à la lecture, où il ne coûte rien.
    """
    if not payload:
        return []
    resultats = ((payload.get("videos") or {}).get("results")) or []
    if not isinstance(resultats, list):
        return []

    videos: list[dict[str, Any]] = []
    for v in resultats:
        if not isinstance(v, dict):
            continue
        site, cle = v.get("site"), v.get("key")
        if not site or not cle:
            continue
        videos.append(
            {
                "site": str(site),
                "cle": str(cle),
                "type": str(v.get("type") or "Autre"),
                "nom": v.get("name") or None,
                "lang": str(v.get("iso_639_1") or ""),
                "officiel": bool(v.get("official")),
                "publie_le": _date(v.get("published_at")),
                "definition": v.get("size") if isinstance(v.get("size"), int) else None,
                "saison": saison,
            }
        )
    return videos


async def projeter_serie(
    conn: psycopg.AsyncConnection, id_tmdb: int, *, saisons: bool = True
) -> int:
    """Projette les vidéos d'une série — sa fiche, et celles de ses saisons.

    Renvoie le nombre de vidéos distinctes retenues. Marque la série comme
    examinée dans tous les cas, y compris quand elle n'en a aucune : sans ça,
    chaque passe rouvrirait les mêmes fiches vides indéfiniment.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            select distinct on (kind, source_id) id, kind, source_id, payload
            from raw_source
            where source = 'tmdb' and http_status between 200 and 299
              and (source_id = %(id)s::text
                   or (%(saisons)s and kind = 'tv_season'
                       and source_id like %(id)s::text || '/%%'))
            order by kind, source_id, fetched_at desc
            """,
            {"id": id_tmdb, "saisons": saisons},
        )
        fiches = await cur.fetchall()

    fiche_serie = next((f for f in fiches if f["kind"] == "tv"), None)
    if fiche_serie is None:
        # Série jamais collectée : rien à projeter, et rien à marquer non plus
        # — la marquer prétendrait qu'on l'a examinée.
        return 0

    # La projection se range sous le pivot, comme `riche_source` et comme la
    # notation. La fiche ayant été collectée, l'œuvre existe déjà — mais on
    # passe par `ensure_oeuvres` plutôt que par une lecture : une base
    # collectée avant le lot 12 n'a de pivot que ce que la migration lui a
    # rattrapé, et une re-projection ne doit pas tomber sur ce trou-là.
    oeuvre_id = (await store.ensure_oeuvres(conn, [id_tmdb]))[id_tmdb]

    videos = extraire(fiche_serie["payload"])
    for f in fiches:
        if f["kind"] != "tv_season":
            continue
        numero = f["source_id"].partition("/s")[2]
        videos += extraire(f["payload"], saison=int(numero) if numero.isdigit() else None)

    async with conn.cursor() as cur:
        for v in videos:
            await cur.execute(
                """
                insert into video (oeuvre_id, site, cle, source, type, nom, lang,
                                   officiel, publie_le, definition, saison, raw_source_id)
                values (%(id)s, %(site)s, %(cle)s, 'tmdb', %(type)s, %(nom)s, %(lang)s,
                        %(officiel)s, %(publie_le)s, %(definition)s, %(saison)s, %(raw)s)
                on conflict (oeuvre_id, site, cle) do update set
                    type = excluded.type, nom = excluded.nom, lang = excluded.lang,
                    officiel = excluded.officiel, publie_le = excluded.publie_le,
                    definition = excluded.definition, raw_source_id = excluded.raw_source_id,
                    fetched_at = now()
                """,
                {**v, "id": oeuvre_id, "raw": fiche_serie["id"]},
            )
        # `saison` volontairement absente du `do update` : une bande-annonce
        # listée sur la série *et* sur une saison garde le rattachement de la
        # première vue, sinon l'ordre de parcours déciderait du résultat.
        await cur.execute(
            """
            insert into video_scan (oeuvre_id, raw_source_id, videos)
            values (%s, %s, %s)
            on conflict (oeuvre_id) do update set
                raw_source_id = excluded.raw_source_id,
                videos = excluded.videos,
                scanned_at = now()
            """,
            (oeuvre_id, fiche_serie["id"], len({(v["site"], v["cle"]) for v in videos})),
        )
    return len({(v["site"], v["cle"]) for v in videos})


_ORDRES = {
    "id": "c.id",
    "popularity": "c.popularity desc nulls last",
    "recent": "c.first_air_date desc nulls last, c.popularity desc nulls last",
    "random": "random()",
}


async def series_a_projeter(
    conn: psycopg.AsyncConnection,
    *,
    limit: int | None = None,
    order: str = "popularity",
    tout: bool = False,
) -> list[int]:
    """Les séries collectées dont les vidéos restent à projeter.

    `tout` reprend aussi celles déjà examinées — utile après une re-collecte,
    ou quand l'extraction elle-même a changé.
    """
    if order not in _ORDRES:
        raise ValueError(f"ordre inconnu : {order} (attendus : {', '.join(_ORDRES)})")

    # `exists` plutôt qu'un `left join` : on ne veut pas dédoublonner derrière
    # une jointure sur `raw_source`, qui est append-only et compte plusieurs
    # lignes par série.
    condition = (
        ""
        if tout
        else """and not exists (
                select 1 from video_scan s
                join oeuvre o on o.id = s.oeuvre_id
                where o.univers = 'series' and o.id_tmdb = c.id)"""
    )
    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            select c.id from tmdb_catalog c
            where c.univers = 'series' and exists (
                select 1 from raw_source r
                where r.source = 'tmdb' and r.kind = 'tv'
                  and r.source_id = c.id::text and r.http_status between 200 and 299
            ) {condition}
            order by {_ORDRES[order]}
            limit %s
            """,
            (limit,),
        )
        return [row[0] for row in await cur.fetchall()]


async def bilan(conn: psycopg.AsyncConnection) -> dict[str, int]:
    """De quoi dire, en fin de passe, ce que le canal couvre réellement."""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            select (select count(*) from video_scan),
                   (select count(*) from video_scan where videos > 0),
                   (select count(*) from video),
                   (select count(*) from video where type = 'Trailer' and officiel),
                   (select count(distinct oeuvre_id) from video where lang = 'fr'),
                   (select count(*) from video where vivante is null),
                   (select count(*) from video where vivante is false)
            """
        )
        row = await cur.fetchone()
    examinees, avec, total, annonces, en_francais, jamais, mortes = row  # type: ignore[misc]
    return {
        "examinees": examinees,
        "avec_video": avec,
        "videos": total,
        "annonces_officielles": annonces,
        "series_en_francais": en_francais,
        "jamais_verifiees": jamais,
        "mortes": mortes,
    }


# ---------------------------------------------------------------------------
# La vérification de validité
# ---------------------------------------------------------------------------

# Les points oEmbed des hébergeurs. Ils ne demandent pas de clé, ne consomment
# aucun quota déclaré, et répondent 200 si et seulement si la vidéo est
# lisible publiquement — ce qui est exactement la question posée. L'API
# YouTube Data ferait la même chose en lots de 50, mais elle exige une clé et
# un projet Google : trop de dépendance pour une vérification d'hygiène.
OEMBED = {
    "YouTube": "https://www.youtube.com/oembed?url=https%3A//www.youtube.com/watch%3Fv%3D{cle}&format=json",
    "Vimeo": "https://vimeo.com/api/oembed.json?url=https%3A//vimeo.com/{cle}",
}


async def videos_a_verifier(
    conn: psycopg.AsyncConnection, *, limit: int | None = None, age_jours: int | None = None
) -> list[tuple[int, str, str]]:
    """Les vidéos à contrôler, les plus anciennement vues d'abord.

    `age_jours` borne la reprise : sans lui, une passe quotidienne revérifierait
    tout le catalogue chaque jour. Avec `--age 30`, elle ne rouvre que ce qui
    n'a pas été vu depuis un mois, et les jamais-vérifiées passent toujours en
    premier.
    """
    condition = "" if age_jours is None else "and (verifiee_le is null or verifiee_le < %(seuil)s)"
    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            select oeuvre_id, site, cle from video
            where site = any(%(sites)s) {condition}
            order by verifiee_le nulls first
            limit %(limit)s
            """,
            {
                "sites": list(OEMBED),
                "limit": limit,
                "seuil": (
                    None
                    if age_jours is None
                    else datetime.now(UTC) - timedelta(days=max(0, age_jours))
                ),
            },
        )
        return [(r[0], r[1], r[2]) for r in await cur.fetchall()]


async def verifier_une(fetcher: Any, site: str, cle: str) -> tuple[bool, int]:
    """Une vidéo est-elle encore lisible ? Renvoie (vivante, code HTTP).

    Tout ce qui n'est pas 200 est traité comme non lisible, sans chercher à
    distinguer « retirée » de « privée » : pour la fiche, la conséquence est la
    même. Le code est conservé quand même — c'est lui qui permettra de dire un
    jour si une chaîne entière a disparu.

    Les erreurs réseau (`status = 0`) ne condamnent pas la vidéo : un
    hébergeur momentanément injoignable ferait autrement disparaître tout le
    catalogue d'un coup.
    """
    resultat = await fetcher.get_json(OEMBED[site].format(cle=cle))
    statut = int(resultat.status)
    if statut == 0 or statut == 429 or statut >= 500:
        raise IndisponibleTemporairement(statut)
    return statut == 200, statut


class IndisponibleTemporairement(Exception):
    """L'hébergeur n'a pas répondu — on ne conclut rien, on réessaiera."""

    def __init__(self, statut: int) -> None:
        super().__init__(f"hébergeur injoignable (statut {statut})")
        self.statut = statut


async def marquer(
    conn: psycopg.AsyncConnection,
    oeuvre_id: int,
    site: str,
    cle: str,
    *,
    vivante: bool,
    statut: int,
) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            "update video set vivante = %s, statut = %s, verifiee_le = now()"
            " where oeuvre_id = %s and site = %s and cle = %s",
            (vivante, statut, oeuvre_id, site, cle),
        )
