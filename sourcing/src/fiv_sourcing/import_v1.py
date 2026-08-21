"""L'import de l'export V1 — membres, tops, découvertes, avis.

L'autre moitié de `tools/export_v1.py` : lui lit la V1 et dépose des JSONL,
ceci lit les JSONL et remplit le schéma `membre`. Les deux sont volontairement
étanches — l'import ne voit jamais la base V1, tout ce qu'il sait tient dans
le répertoire d'export, et c'est ce qui le rend jouable sur le serveur où la
V1 n'existe pas.

Rejouable par construction : chaque table s'écrit en `on conflict … do update`
sur sa clé V1, et les œuvres créées sans identifiant TMDB — qui n'ont aucune
clé naturelle — passent par le registre `membre.oeuvre_v1`, seul témoin de
leur existence. Deux passes de suite ne changent aucun compte.

L'ordre des phases est celui des dépendances, pas du goût :

    œuvres → membres → identifiants → fives → positions → découvertes → avis

Les œuvres d'abord parce que tout le reste pointe `oeuvre_id` ; les positions
après les fives parce qu'elles portent leur clé ; les avis en dernier avec une
seconde passe pour `reponse_a` (un fil ne se recoud qu'une fois tous ses
messages présents).
"""

from __future__ import annotations

import html
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)

UNIVERS = ("series", "movies")
FICHIER_OEUVRES = {"series": "oeuvres-series.jsonl", "movies": "oeuvres-films.jsonl"}

_ARTICLES = re.compile(r"^(le|la|les|l|un|une|des|the|a|an|el|los|las|il|lo|der|die|das)\s+", re.I)
_PONCTUATION = re.compile(r"[^a-z0-9 ]+")
_BALISES = re.compile(r"<[^>]+>")


def normaliser_titre(titre: str | None) -> str | None:
    """« L'Île aux enfants » et « ile aux enfants  » doivent se retrouver.

    Minuscules, accents décomposés puis jetés, ponctuation effacée, article de
    tête retiré, espaces resserrées. Volontairement rustique : le rapprochement
    exige ensuite l'année à ±1 et un candidat unique — c'est la combinaison qui
    protège, pas la sophistication de la normalisation.
    """
    if not titre:
        return None
    t = unicodedata.normalize("NFKD", titre.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("'", " ").replace("’", " ").replace("´", " ")
    t = _PONCTUATION.sub(" ", t)
    t = _ARTICLES.sub("", t.strip())
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def texte_sans_html(brut: str | None) -> str | None:
    """Les descriptions V1 sont du HTML échappé (`<p>`, `&#39;`) — on désamorce."""
    if not brut:
        return None
    t = html.unescape(brut)
    t = _BALISES.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip() or None


def lire_jsonl(chemin: Path):
    with chemin.open(encoding="utf-8") as f:
        for ligne in f:
            if ligne.strip():
                yield json.loads(ligne)


@dataclass
class RapportImport:
    """Ce qui s'est passé, phase par phase — imprimé tel quel par la CLI."""

    oeuvres_tmdb: int = 0  # résolues par identifiant TMDB
    oeuvres_titre: int = 0  # rapprochées par titre + année
    oeuvres_creees: int = 0  # créées en V2 depuis leur fiche V1
    a_collecter: dict[str, list[int]] = field(default_factory=dict)
    membres: int = 0
    identifiants: int = 0
    fives: int = 0
    positions: int = 0
    positions_ecartees: int = 0  # vides, illisibles, orphelines, doublons
    decouvertes: int = 0
    decouvertes_ecartees: int = 0
    avis: int = 0
    avis_ecartes: int = 0
    reponses_recousues: int = 0


# ------------------------------------------------------------------ œuvres


async def _resoudre_par_tmdb(
    conn: psycopg.AsyncConnection, univers: str, ids_tmdb: list[int]
) -> tuple[dict[int, int], list[int]]:
    """id TMDB → oeuvre_id, en créant le pivot au besoin.

    Créer le pivot ici est légitime — c'est ce que fait déjà l'enrichissement
    (`ensure_oeuvres`) : une œuvre existe dès qu'on sait qu'elle existe, sa
    fiche arrive quand elle arrive. Ce qui manque encore à la collecte est
    rendu à l'appelant pour finir dans `a-collecter-<univers>.txt`.
    """
    if not ids_tmdb:
        return {}, []
    async with conn.cursor() as cur:
        await cur.execute(
            "select id_tmdb from oeuvre where univers = %s and id_tmdb = any(%s)",
            (univers, ids_tmdb),
        )
        deja_la = {r[0] for r in await cur.fetchall()}
        await cur.execute(
            """
            insert into oeuvre (univers, id_tmdb)
            select %s, unnest(%s::int[])
            on conflict do nothing
            """,
            (univers, ids_tmdb),
        )
        await cur.execute(
            "select id_tmdb, id from oeuvre where univers = %s and id_tmdb = any(%s)",
            (univers, ids_tmdb),
        )
        mapping = {r[0]: r[1] for r in await cur.fetchall()}
    return mapping, sorted(set(ids_tmdb) - deja_la)


async def _apparier_par_titre(
    conn: psycopg.AsyncConnection, univers: str, oeuvre: dict
) -> int | None:
    """Rapprochement titre normalisé + année ±1, candidat unique ou rien.

    Le biais est voulu : un mauvais appariement fait dire à un membre qu'il
    aime une œuvre qu'il n'a pas citée ; un doublon ne dit rien de faux. Donc
    au moindre doute — pas d'année, plusieurs candidats — on ne rapproche pas,
    on crée.
    """
    annee = oeuvre.get("annee")
    variantes = {
        v
        for v in (
            normaliser_titre(t)
            for t in [*oeuvre.get("titre", {}).values(), *oeuvre.get("titres_alternatifs", [])]
        )
        if v
    }
    if not variantes or not annee:
        return None

    candidats: set[int] = set()  # id TMDB des candidats retenus
    async with conn.cursor() as cur:
        await cur.execute(
            """
            select id, original_name from tmdb_catalog
             where univers = %s
               and first_air_date between make_date(%s, 1, 1) and make_date(%s, 12, 31)
            """,
            (univers, annee - 1, annee + 1),
        )
        for id_tmdb, nom in await cur.fetchall():
            if normaliser_titre(nom) in variantes:
                candidats.add(id_tmdb)

    if len(candidats) != 1:
        return None
    id_tmdb = candidats.pop()
    mapping, _ = await _resoudre_par_tmdb(conn, univers, [id_tmdb])
    return mapping.get(id_tmdb)


async def _creer_oeuvre(conn: psycopg.AsyncConnection, univers: str, oeuvre: dict) -> int:
    """L'œuvre entre en V2 depuis sa fiche V1 — id TMDB null, fiche déposée.

    Le brut va dans `raw_source` (c'est du brut : la fiche V1 telle quelle),
    le lisible dans `riche_source` sous la source `fivorites_v1`. Si TMDB la
    publie un jour, `id_tmdb` se complètera par coalesce sans rien casser.
    """
    fiche = oeuvre.get("fiche") or {}
    titres = oeuvre.get("titre", {})
    titre = titres.get("frFR") or titres.get("enUS") or next(iter(titres.values()), None)

    async with conn.cursor() as cur:
        await cur.execute(
            "insert into oeuvre (univers, titre, annee) values (%s, %s, %s) returning id",
            (univers, titre, oeuvre.get("annee")),
        )
        oeuvre_id = (await cur.fetchone())[0]

        # Même sérialisation canonique que store.payload_digest : deux passes
        # donnent la même empreinte, et l'index de dédoublonnage fait le reste.
        blob = json.dumps(fiche, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        await cur.execute(
            """
            insert into raw_source (source, kind, source_id, lang, http_status,
                                    payload, payload_sha256)
            values ('fivorites_v1', %s, %s, 'fr', 200, %s, sha256(convert_to(%s, 'UTF8')))
            on conflict do nothing
            returning id
            """,
            (univers, str(oeuvre["v1_id"]), Jsonb(fiche), blob),
        )
        ligne = await cur.fetchone()
        if ligne is None:  # déjà déposée par une passe précédente
            await cur.execute(
                """
                select id from raw_source
                 where source = 'fivorites_v1' and kind = %s and source_id = %s
                 order by fetched_at desc limit 1
                """,
                (univers, str(oeuvre["v1_id"])),
            )
            ligne = await cur.fetchone()
        raw_id = ligne[0] if ligne else None

        # Les facts respectent le schéma canonique de normalize.py : une clé
        # sans valeur est absente, aucune clé hors schéma. Le reste de la
        # fiche (acteurs, genres, saisons) vit dans le brut ci-dessus.
        facts: dict[str, Any] = {}
        if titre:
            facts["titre"] = titre
        alternatifs = [t for t in titres.values() if t and t != titre]
        alternatifs += [t for t in oeuvre.get("titres_alternatifs", []) if t]
        if alternatifs:
            facts["titres_alternatifs"] = alternatifs
        if oeuvre.get("annee"):
            facts["annee"] = oeuvre["annee"]

        await cur.execute(
            """
            insert into riche_source (oeuvre_id, raw_source_id, source, lang, source_id,
                                      content, media, facts, resolved_by, fetched_at)
            values (%s, %s, 'fivorites_v1', 'fr', %s, %s, %s, %s, 'import_v1', now())
            on conflict (oeuvre_id, source, lang) do update set
                raw_source_id = excluded.raw_source_id,
                content       = excluded.content,
                media         = excluded.media,
                facts         = excluded.facts,
                fetched_at    = now()
            """,
            (
                oeuvre_id,
                raw_id,
                str(oeuvre["v1_id"]),
                texte_sans_html((fiche.get("description") or {}).get("frFR")),
                Jsonb(fiche.get("images") or []),
                Jsonb(facts),
            ),
        )
    return oeuvre_id


async def importer_oeuvres(
    conn: psycopg.AsyncConnection, dossier: Path, rapport: RapportImport
) -> dict[tuple[str, int], int]:
    """Toutes les œuvres de l'export trouvent un `oeuvre_id` — d'une façon ou
    d'une autre. Rend la correspondance (univers, v1_id canonique) → oeuvre_id,
    qui est aussi écrite dans `membre.oeuvre_v1` pour les passes suivantes."""
    correspondance: dict[tuple[str, int], int] = {}

    async with conn.cursor() as cur:
        await cur.execute("select univers, v1_id, oeuvre_id from membre.oeuvre_v1")
        for univers, v1_id, oeuvre_id in await cur.fetchall():
            correspondance[(univers, v1_id)] = oeuvre_id

    for univers in UNIVERS:
        oeuvres = list(lire_jsonl(dossier / FICHIER_OEUVRES[univers]))

        avec_tmdb = [o for o in oeuvres if o["id_tmdb"] is not None]
        mapping, absents = await _resoudre_par_tmdb(
            conn, univers, sorted({o["id_tmdb"] for o in avec_tmdb})
        )
        if absents:
            rapport.a_collecter[univers] = absents
        lot = []
        for o in avec_tmdb:
            oeuvre_id = mapping[o["id_tmdb"]]
            correspondance[(univers, o["v1_id"])] = oeuvre_id
            lot.append((univers, o["v1_id"], oeuvre_id, o["id_tmdb"], "tmdb"))
            rapport.oeuvres_tmdb += 1

        for o in oeuvres:
            if o["id_tmdb"] is not None:
                continue
            cle = (univers, o["v1_id"])
            if cle in correspondance:  # passe précédente — le registre sait
                continue
            oeuvre_id = await _apparier_par_titre(conn, univers, o)
            if oeuvre_id is not None:
                methode = "titre"
                rapport.oeuvres_titre += 1
            else:
                oeuvre_id = await _creer_oeuvre(conn, univers, o)
                methode = "cree"
                rapport.oeuvres_creees += 1
            correspondance[cle] = oeuvre_id
            lot.append((univers, o["v1_id"], oeuvre_id, None, methode))

        async with conn.cursor() as cur:
            await cur.executemany(
                """
                insert into membre.oeuvre_v1 (univers, v1_id, oeuvre_id, id_tmdb, methode)
                values (%s, %s, %s, %s, %s)
                on conflict (univers, v1_id) do nothing
                """,
                lot,
            )
    return correspondance


# ------------------------------------------------------------------ membres


async def importer_membres(
    conn: psycopg.AsyncConnection, dossier: Path, rapport: RapportImport
) -> None:
    lot_membres, lot_identifiants = [], []
    for u in lire_jsonl(dossier / "utilisateurs.jsonl"):
        profil = dict(u["profil"])
        profil["emails_secondaires"] = u.get("emails_secondaires") or []
        profil["acquisition"] = u.get("acquisition") or {}
        lot_membres.append(
            (
                u["v1_id"],
                u["pseudo"],
                Jsonb(profil),
                u["statut"]["valide"],
                u["statut"]["bani"],
                u["statut"].get("privacy_defaut_v1"),
                u["dates"]["creation"],
                u["dates"]["derniere_maj"],
                u["dates"]["derniere_connexion"],
            )
        )
        # L'email n'est un identifiant que s'il vient d'un compte : les
        # adresses de `personnes.emails` ne sont pas uniques (159 partages,
        # décision : pas de fusion), celles de `users_auth` le sont.
        if u["a_un_compte"] and u.get("email"):
            lot_identifiants.append((u["v1_id"], u["email"], u["dates"]["creation"]))

    async with conn.cursor() as cur:
        # `masque` n'est ni inséré ni mis à jour, et les deux comptent : à
        # l'insertion le défaut du schéma (`true`) s'applique — un membre de la
        # V1 arrive masqué, migration 014 ; à la mise à jour, l'absence de la
        # colonne préserve un démasquage décidé depuis. Un ré-import ne
        # republie donc personne.
        await cur.executemany(
            """
            insert into membre.membre (v1_id, pseudo, profil, valide, bani, privacy_v1,
                                       creation, derniere_maj, derniere_connexion)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (v1_id) do update set
                pseudo = excluded.pseudo, profil = excluded.profil,
                valide = excluded.valide, bani = excluded.bani,
                privacy_v1 = excluded.privacy_v1,
                derniere_maj = excluded.derniere_maj,
                derniere_connexion = excluded.derniere_connexion
            """,
            lot_membres,
        )
        rapport.membres = len(lot_membres)

        await cur.executemany(
            """
            insert into membre.identifiant (membre_id, email, creation)
            select m.id, %(email)s, %(creation)s from membre.membre m where m.v1_id = %(v1_id)s
            on conflict (membre_id) do update set email = excluded.email
            """,
            [{"v1_id": v, "email": e, "creation": c} for v, e, c in lot_identifiants],
        )
        rapport.identifiants = len(lot_identifiants)


# ------------------------------------------------------------------ fives


async def importer_fives(
    conn: psycopg.AsyncConnection,
    dossier: Path,
    correspondance: dict[tuple[str, int], int],
    rapport: RapportImport,
) -> None:
    async with conn.cursor() as cur:
        await cur.execute("select v1_id, id from membre.membre where v1_id is not null")
        membres = {r[0]: r[1] for r in await cur.fetchall()}

    fives, positions = [], []
    for f in lire_jsonl(dossier / "fives.jsonl"):
        membre_id = membres.get(f["user_v1_id"])
        if membre_id is None:
            continue
        fives.append(
            (
                f["v1_five_id"],
                membre_id,
                f["univers"],
                f["periode"],
                f.get("privacy_v1"),
                f.get("titre"),
                f["valide"],
                f["dates"]["creation"],
                f["dates"]["derniere_maj"],
            )
        )
        for p in f["positions"]:
            if p.get("statut") or p.get("doublon_de"):
                rapport.positions_ecartees += 1
                continue
            oeuvre_id = correspondance.get((f["univers"], p["canonique_v1_id"]))
            if oeuvre_id is None:
                rapport.positions_ecartees += 1
                continue
            positions.append(
                (
                    f["v1_five_id"],
                    p["rang"],
                    oeuvre_id,
                    p.get("titre_saisi"),
                    p.get("pourquoi"),
                    p.get("commentaire"),
                )
            )

    async with conn.cursor() as cur:
        await cur.executemany(
            """
            insert into membre.five (v1_id, membre_id, univers, periode, privacy_v1,
                                     titre, valide, creation, derniere_maj)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (v1_id) do update set
                periode = excluded.periode, privacy_v1 = excluded.privacy_v1,
                titre = excluded.titre, valide = excluded.valide,
                derniere_maj = excluded.derniere_maj
            """,
            fives,
        )
        rapport.fives = len(fives)

        await cur.executemany(
            """
            insert into membre.five_position (five_id, rang, oeuvre_id,
                                              titre_saisi, pourquoi, commentaire)
            select f.id, %(rang)s, %(oeuvre)s, %(titre)s, %(pourquoi)s, %(commentaire)s
              from membre.five f where f.v1_id = %(five_v1)s
            on conflict (five_id, rang) do update set
                oeuvre_id = excluded.oeuvre_id, titre_saisi = excluded.titre_saisi,
                pourquoi = excluded.pourquoi, commentaire = excluded.commentaire
            """,
            [
                {"five_v1": fv, "rang": r, "oeuvre": o, "titre": t, "pourquoi": p, "commentaire": c}
                for fv, r, o, t, p, c in positions
            ],
        )
        rapport.positions = len(positions)


# ------------------------------------------------------------------ le reste


async def importer_decouvertes(
    conn: psycopg.AsyncConnection,
    dossier: Path,
    correspondance: dict[tuple[str, int], int],
    rapport: RapportImport,
) -> None:
    async with conn.cursor() as cur:
        await cur.execute("select v1_id, id from membre.membre where v1_id is not null")
        membres = {r[0]: r[1] for r in await cur.fetchall()}

    lot = []
    for d in lire_jsonl(dossier / "decouvertes.jsonl"):
        membre_id = membres.get(d["user_v1_id"])
        canonique = d.get("canonique_v1_id")
        oeuvre_id = correspondance.get((d["univers"], canonique)) if canonique else None
        if membre_id is None or oeuvre_id is None:
            rapport.decouvertes_ecartees += 1
            continue
        lot.append((membre_id, oeuvre_id, Jsonb(d.get("origine")), d["creation"], d["valide"]))

    # Trié par date : en cas de doublon (même membre, même œuvre découverte
    # deux fois en V1), c'est la première découverte qui reste.
    lot.sort(key=lambda x: x[3] or "")
    async with conn.cursor() as cur:
        await cur.executemany(
            """
            insert into membre.decouverte (membre_id, oeuvre_id, origine, creation, valide)
            values (%s, %s, %s, %s, %s)
            on conflict (membre_id, oeuvre_id) do nothing
            """,
            lot,
        )
        rapport.decouvertes = len(lot)


async def importer_avis(
    conn: psycopg.AsyncConnection,
    dossier: Path,
    correspondance: dict[tuple[str, int], int],
    rapport: RapportImport,
) -> None:
    async with conn.cursor() as cur:
        await cur.execute("select v1_id, id from membre.membre where v1_id is not null")
        membres = {r[0]: r[1] for r in await cur.fetchall()}

    lot, fils = [], []
    for a in lire_jsonl(dossier / "avis.jsonl"):
        membre_id = membres.get(a["user_v1_id"])
        canonique = a.get("canonique_v1_id")
        oeuvre_id = correspondance.get((a["univers"], canonique)) if canonique else None
        if membre_id is None or oeuvre_id is None:
            rapport.avis_ecartes += 1
            continue
        lot.append(
            (
                a["univers"],
                a["v1_avis_id"],
                membre_id,
                oeuvre_id,
                a.get("note"),
                a.get("titre"),
                a.get("texte"),
                a["valide"],
                a["dates"]["creation"],
                a["dates"]["derniere_maj"],
            )
        )
        if a.get("reponse_a") is not None:
            fils.append((a["univers"], a["v1_avis_id"], a["reponse_a"]))

    async with conn.cursor() as cur:
        await cur.executemany(
            """
            insert into membre.avis (v1_univers, v1_id, membre_id, oeuvre_id, note,
                                     titre, texte, valide, creation, derniere_maj)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (v1_univers, v1_id) do update set
                note = excluded.note, titre = excluded.titre, texte = excluded.texte,
                valide = excluded.valide, derniere_maj = excluded.derniere_maj
            """,
            lot,
        )
        rapport.avis = len(lot)

        # Seconde passe : les fils. `reponse_a` de la V1 désigne un avis V1 —
        # on ne peut le traduire qu'une fois tous les avis en place.
        await cur.executemany(
            """
            update membre.avis a set reponse_a = cible.id
              from membre.avis cible
             where a.v1_univers = %(u)s and a.v1_id = %(moi)s
               and cible.v1_univers = %(u)s and cible.v1_id = %(cible)s
            """,
            [{"u": u, "moi": m, "cible": c} for u, m, c in fils],
        )
        rapport.reponses_recousues = len(fils)


# ------------------------------------------------------------------ l'entrée


async def importer(conn: psycopg.AsyncConnection, dossier: Path) -> RapportImport:
    """Joue l'import complet depuis un répertoire d'export V1.

    Chaque phase est sa propre transaction : une interruption laisse les
    phases faites, faites — et la reprise est un simple relancement, le
    `on conflict` absorbant tout ce qui existe déjà.
    """
    manifest = json.loads((dossier / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("partiel"):
        raise ValueError("cet export est partiel (--limite) : on n'importe pas un essai")

    rapport = RapportImport()

    async with conn.transaction():
        correspondance = await importer_oeuvres(conn, dossier, rapport)
    async with conn.transaction():
        await importer_membres(conn, dossier, rapport)
    async with conn.transaction():
        await importer_fives(conn, dossier, correspondance, rapport)
    async with conn.transaction():
        await importer_decouvertes(conn, dossier, correspondance, rapport)
    async with conn.transaction():
        await importer_avis(conn, dossier, correspondance, rapport)

    # La liste de ce que la collecte n'a pas encore : à passer à
    # `tmdb fetch --id` (les pivots existent déjà, seule la fiche manque).
    for univers, ids in rapport.a_collecter.items():
        chemin = dossier / f"a-collecter-{univers}.txt"
        chemin.write_text("\n".join(str(i) for i in ids) + "\n", encoding="utf-8")
        log.info("%d fiches %s à collecter — liste dans %s", len(ids), univers, chemin)

    return rapport
