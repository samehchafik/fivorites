#!/usr/bin/env python3
"""L'export de la V1 — un JSONL par type, prêt pour l'import V2.

    ./tools/export_v1.py --out ~/travail/export-v1
    ./tools/export_v1.py --out /tmp/essai --limite 500     # une passe d'essai

Ce que fait ce script, et ce qu'il ne fait pas : il **lit** la base V1 et
dépose des fichiers. Il n'écrit rien en V2, ne devine rien, n'apparie rien par
le titre — l'appariement est le lot suivant, et il a besoin que celui-ci soit
honnête plutôt que malin.

Trois règles portent tout le fichier, elles sont détaillées dans
`doc/migration-v1-v2.md` :

1. **Les redirections `_301` sont suivies avant toute chose.** La V1 a fusionné
   des fiches en pointant la morte vers la vivante ; « La casa de papel » vit
   sous deux identifiants. Ne pas suivre, c'est deux œuvres V2 là où le membre
   en a cité une — et cinq points d'appariement perdus.
2. **Le rang d'une œuvre dans un top est un signal, pas un détail
   d'affichage.** Il ne survit que si l'export l'écrit : `tops` est un tableau,
   son ordre est la seule information de classement qui existe.
3. **Seules les œuvres citées sortent.** 374 028 fiches en V1, ~9 500 citées :
   la V2 a déjà collecté le reste depuis TMDB, le recopier serait du bruit.

Les fichiers produits (comptes mesurés sur l'instantané du 2021-02-23) :

    manifest.json                    la date, la source, les comptes, les empreintes
    utilisateurs.jsonl               69 355 — invités compris, c'est voulu
    oeuvres-series.jsonl              3 564 — correspondance, + fiche si pas d'id TMDB
    oeuvres-films.jsonl               5 989
    fives.jsonl                      66 878 — les tops, positions à plat, « pourquoi » joint
    decouvertes.jsonl                92 324
    avis.jsonl                          287
    a-reconcilier.jsonl                     — ce qui ne s'apparie pas tout seul
    secrets/authentification.jsonl   32 349 — mode 600, hors dépôt, effacé après usage

Le script n'a besoin que de psycopg. Sur ce poste :

    /Users/…/Fivorites.v2/sourcing/.venv/bin/python tools/export_v1.py --out …
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

DSN_DEFAUT = "postgres://fivorites:fivorites@localhost:5432/fivorites"
UNIVERS = ("series", "movies")          # nom d'univers V2 = nom de schéma V1
FICHIER_OEUVRES = {"series": "oeuvres-series.jsonl", "movies": "oeuvres-films.jsonl"}
ENTIER = re.compile(r"^[0-9]+$")


# ----------------------------------------------------------------- écriture

def _json_defaut(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError(f"non sérialisable : {type(o)}")


class Sortie:
    """Un fichier JSONL qui se compte et s'empreinte en s'écrivant.

    L'empreinte va au manifest : c'est ce qui permet de dire, trois semaines
    plus tard, si le fichier importé est bien celui qui a été exporté.
    """

    def __init__(self, chemin: Path, mode: int = 0o644):
        self.chemin = chemin
        self.lignes = 0
        self._h = hashlib.sha256()
        chemin.parent.mkdir(parents=True, exist_ok=True)
        self._f = chemin.open("w", encoding="utf-8")
        os.chmod(chemin, mode)

    def ecrire(self, obj) -> None:
        ligne = json.dumps(obj, ensure_ascii=False, default=_json_defaut) + "\n"
        self._f.write(ligne)
        self._h.update(ligne.encode("utf-8"))
        self.lignes += 1

    def fermer(self) -> dict:
        self._f.close()
        return {"lignes": self.lignes, "sha256": self._h.hexdigest()}


def texte_multilingue(j) -> dict:
    """`{"frFR": {"text": "…", "phonem": "…"}}` → `{"frFR": "…"}`.

    La V1 range un objet par langue avec du phonème dedans ; seul le texte
    nous intéresse, et une chaîne vide vaut une absence.
    """
    if not isinstance(j, dict):
        return {}
    out = {}
    for lang, v in j.items():
        t = v.get("text") if isinstance(v, dict) else v
        if isinstance(t, str) and t.strip():
            out[lang] = t.strip()
    return out


def premier_texte(j) -> str | None:
    d = texte_multilingue(j)
    for lang in ("frFR", "enUS"):
        if lang in d:
            return d[lang]
    return next(iter(d.values()), None)


def annee_int(v) -> int | None:
    if v is None:
        return None
    m = re.search(r"(1[89]\d{2}|20\d{2})", str(v))
    return int(m.group(1)) if m else None


# ----------------------------------------------------------------- œuvres

CHAMPS_FICHE = {
    "series": ("description, auteurs, realisateur, acteurs, productions, categorie, "
               "duree, langues, distributeurs, musiques, saisons, number_of_seasons, "
               "number_of_episodes, original_name, first_air_date"),
    "movies": ("description, auteurs, realisateur, acteurs, productions, categorie, "
               "duree, langues, distributeurs, musiques, release_date"),
}


def citations(cur) -> dict[tuple[str, int], int]:
    """Combien de fois chaque fiche V1 est citée, tous tops valides confondus.

    Les découvertes et les avis comptent pour zéro : ils ne pèsent pas dans
    `nb_citations`, mais l'œuvre qu'ils référencent doit sortir quand même —
    3 963 découvertes pointent des œuvres qui ne sont dans aucun top, et sans
    ligne dans `oeuvres-*.jsonl` l'import ne saurait pas les résoudre.
    """
    cur.execute(
        """
        SELECT c.categorie[1] AS univers,
               (x.top::jsonb->>'id')::int AS v1_id,
               count(*) AS n
          FROM fives.catalog c,
               unnest(c.tops) WITH ORDINALITY AS x(top, rang)
         WHERE c.valide
           AND c.categorie[1] = ANY(%s)
           AND x.top::jsonb->>'id' ~ '^[0-9]+$'
         GROUP BY 1, 2
        """,
        (list(UNIVERS),),
    )
    cites = {(r["univers"], r["v1_id"]): r["n"] for r in cur.fetchall()}

    cur.execute(
        "SELECT DISTINCT schemas AS univers, id AS v1_id FROM public.users_decouverte "
        "WHERE schemas = ANY(%s)", (list(UNIVERS),))
    for r in cur.fetchall():
        cites.setdefault((r["univers"], r["v1_id"]), 0)
    for univers in UNIVERS:
        cur.execute(f"SELECT DISTINCT id_catalog FROM {univers}.reviews")
        for r in cur.fetchall():
            cites.setdefault((univers, r["id_catalog"]), 0)
    return cites


def charger_fiches(cur, univers: str, ids: list[int]) -> dict[int, dict]:
    if not ids:
        return {}
    cur.execute(
        f"""
        SELECT id,
               coalesce(nullif(_301, 0), id) AS canonique,
               source_acquisition->>'id'     AS id_tmdb,
               titre, annee, valide, alternative_titles
          FROM {univers}.catalog
         WHERE id = ANY(%s)
        """,
        (ids,),
    )
    return {r["id"]: r for r in cur.fetchall()}


def exporter_oeuvres(cur, dossier: Path, cites: dict, recon: Sortie) -> tuple[dict, dict]:
    """Écrit les deux fichiers d'œuvres, rend la table de résolution.

    La résolution `(univers, v1_id) -> {canonique, id_tmdb}` sert ensuite aux
    tops, aux découvertes et aux avis : tous citent une fiche V1, aucun n'a à
    savoir qu'elle a été redirigée.
    """
    resolution: dict[tuple[str, int], dict] = {}
    manifeste: dict[str, dict] = {}

    for univers in UNIVERS:
        ids = sorted(v for (u, v) in cites if u == univers)
        fiches = charger_fiches(cur, univers, ids)

        # Le maître d'une fiche redirigée n'est pas forcément cité lui-même.
        manquants = sorted({f["canonique"] for f in fiches.values()} - set(fiches))
        fiches |= charger_fiches(cur, univers, manquants)

        # Regroupement des citations sous la fiche canonique.
        alias: dict[int, list[int]] = defaultdict(list)
        compte: dict[int, int] = defaultdict(int)
        for v1_id in ids:
            f = fiches.get(v1_id)
            if f is None:                       # citation vers une fiche disparue
                recon.ecrire({"type": "fiche_absente", "univers": univers,
                              "v1_id": v1_id, "citations": cites[(univers, v1_id)]})
                continue
            canon = f["canonique"] if f["canonique"] in fiches else v1_id
            alias[canon].append(v1_id)
            compte[canon] += cites[(univers, v1_id)]
            resolution[(univers, v1_id)] = {
                "canonique": canon,
                "id_tmdb": int(fiches[canon]["id_tmdb"]) if _tmdb(fiches[canon]) else None,
            }

        sans_tmdb = [c for c in compte if not _tmdb(fiches[c])]
        detail = charger_detail(cur, univers, sans_tmdb)

        sortie = Sortie(dossier / FICHIER_OEUVRES[univers])
        for canon in sorted(compte):
            f = fiches[canon]
            rec = {
                "univers": univers,
                "v1_id": canon,
                "id_tmdb": int(f["id_tmdb"]) if _tmdb(f) else None,
                "canonique_v1_id": canon,
                "alias_v1_ids": sorted(a for a in alias[canon] if a != canon),
                "titre": texte_multilingue(f["titre"]),
                "titres_alternatifs": f["alternative_titles"] or [],
                "annee": annee_int(f["annee"]),
                "nb_citations": compte[canon],
                "valide": f["valide"],
            }
            if rec["id_tmdb"] is None:
                rec["fiche"] = detail.get(canon, {})
                recon.ecrire({"type": "oeuvre_sans_id_tmdb", "univers": univers,
                              "v1_id": canon, "titre": premier_texte(f["titre"]),
                              "annee": rec["annee"], "citations": compte[canon]})
            sortie.ecrire(rec)
        manifeste[FICHIER_OEUVRES[univers]] = sortie.fermer()

    return resolution, manifeste


def _tmdb(fiche) -> bool:
    v = fiche.get("id_tmdb")
    return bool(v) and bool(ENTIER.match(str(v)))


def charger_detail(cur, univers: str, ids: list[int]) -> dict[int, dict]:
    """La fiche complète des œuvres sans id TMDB — celles que la V2 devra créer.

    Elles sont peu nombreuses (932 au total) et ce sont les seules pour
    lesquelles la V1 est la source : d'où le détail, affiche comprise.
    """
    if not ids:
        return {}
    cur.execute(
        f"SELECT id, {CHAMPS_FICHE[univers]} FROM {univers}.catalog WHERE id = ANY(%s)",
        (ids,),
    )
    fiches = {}
    for r in cur.fetchall():
        d = {
            "description": texte_multilingue(r["description"]),
            "realisateur": r["realisateur"],
            "auteurs": r["auteurs"] or [],
            "acteurs": r["acteurs"] or [],
            "productions": r["productions"] or [],
            "genres": r["categorie"] or [],
            "duree": r["duree"],
            "langues": [l.get("text") for l in (r["langues"] or []) if isinstance(l, dict)],
            "distributeurs": r["distributeurs"] or [],
            "musiques": r["musiques"] or [],
            "images": [],
        }
        if univers == "series":
            d["saisons"] = r["saisons"] or []
            d["nb_saisons"] = r["number_of_seasons"]
            d["nb_episodes"] = r["number_of_episodes"]
            d["titre_original"] = r["original_name"]
            d["premiere_diffusion"] = r["first_air_date"]
        else:
            d["date_sortie"] = r["release_date"]
        fiches[r["id"]] = d

    cur.execute(
        f"""
        SELECT id_catalog, image_type::text AS type, src, lang, defaut, priority
          FROM {univers}.catalog_medias
         WHERE id_catalog = ANY(%s) AND valide AND src IS NOT NULL AND src <> ''
         ORDER BY id_catalog, defaut DESC NULLS LAST, priority DESC
        """,
        (ids,),
    )
    for r in cur.fetchall():
        f = fiches.get(r["id_catalog"])
        if f is None:
            continue
        # `src` est tantôt une URL TMDB, tantôt un fichier posé sur le disque
        # de la V1 (`public/series/…`). L'import saura quoi faire de chacun,
        # à condition qu'on le lui dise.
        f["images"].append({
            "type": r["type"],
            "src": r["src"],
            "distant": r["src"].startswith("http"),
            "lang": r["lang"],
            "defaut": bool(r["defaut"]),
        })
    for f in fiches.values():
        f["affiche"] = next((i["src"] for i in f["images"] if i["type"] == "image"), None)
    return fiches


# ----------------------------------------------------------------- membres

def exporter_utilisateurs(conn, dossier: Path, limite: int | None) -> dict:
    sortie = Sortie(dossier / "utilisateurs.jsonl")
    sql = """
        SELECT p.id, p.pseudo, p.prenom, p.nom, p.emails, p.bio, p.genre::text AS genre,
               p.date_naissances, p.visuel, p.socials, p.link_ig, p.link_website,
               p.link_youtube_channel, p.note, p.nb_reviews, p.nb_followers,
               p.valide, p.bani, p.status::text AS privacy, p.utm_source, p.utm_campaign,
               p.creation, p.last_update,
               a.id IS NOT NULL AS a_un_compte, a.email, a.last_connexion
          FROM public.personnes p
          LEFT JOIN public.users_auth a ON a.id = p.id
         ORDER BY p.id
    """
    with conn.cursor("cur_users", row_factory=dict_row) as cur:
        cur.execute(sql)
        for i, r in enumerate(cur):
            if limite and i >= limite:
                break
            emails = [e for e in (r["emails"] or []) if e and e.strip()]
            principal = r["email"] or (emails[0] if emails else None)
            sortie.ecrire({
                "v1_id": r["id"],
                "pseudo": r["pseudo"],
                "email": principal,
                "emails_secondaires": [e for e in emails if e != principal],
                "a_un_compte": r["a_un_compte"],
                "profil": {
                    "prenom": r["prenom"], "nom": r["nom"], "bio": r["bio"],
                    "genre": r["genre"], "date_naissance": r["date_naissances"],
                    "avatar": r["visuel"], "socials": r["socials"] or [],
                    "liens": {"ig": r["link_ig"], "website": r["link_website"],
                              "youtube": r["link_youtube_channel"]},
                },
                "compteurs": {"nb_reviews": r["nb_reviews"], "note": r["note"],
                              "nb_followers_v1": r["nb_followers"]},
                "statut": {"valide": r["valide"], "bani": r["bani"],
                           "privacy_defaut_v1": r["privacy"]},
                "acquisition": {"utm_source": r["utm_source"],
                                "utm_campaign": r["utm_campaign"]},
                "dates": {"creation": r["creation"], "derniere_maj": r["last_update"],
                          "derniere_connexion": r["last_connexion"]},
            })
    return {"utilisateurs.jsonl": sortie.fermer()}


def exporter_secrets(conn, dossier: Path) -> dict:
    """Les condensats SHA-256 de la V1, à part et en 600.

    Ils n'entrent pas en V2 : l'authentification n'est pas écrite, et un
    SHA-256 non salé ne se recycle pas. Ce fichier existe pour le jour où la
    question se posera, et s'efface le jour où elle est tranchée.
    """
    (dossier / "secrets").mkdir(parents=True, exist_ok=True)
    os.chmod(dossier / "secrets", 0o700)
    sortie = Sortie(dossier / "secrets" / "authentification.jsonl", mode=0o600)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, email, password, email_valide, valide, bani, "
                    "creation, last_connexion FROM public.users_auth ORDER BY id")
        for r in cur:
            sortie.ecrire({"v1_id": r["id"], "email": r["email"],
                           "sha256": r["password"], "email_valide": r["email_valide"],
                           "valide": r["valide"], "bani": r["bani"],
                           "creation": r["creation"], "derniere_connexion": r["last_connexion"]})
    return {"secrets/authentification.jsonl": sortie.fermer()}


# ----------------------------------------------------------------- tops

def charger_pourquoi(conn) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT id_five, id_catalog, schemas, why
              FROM fives.catalog_user_why
             WHERE schemas = ANY(%s) AND valide AND why IS NOT NULL AND why <> ''
        """, (list(UNIVERS),))
        return {(r["id_five"], r["id_catalog"], r["schemas"]): r["why"] for r in cur}


def exporter_fives(conn, dossier: Path, resolution: dict, recon: Sortie) -> dict:
    pourquoi = charger_pourquoi(conn)
    consommes: set = set()
    sortie = Sortie(dossier / "fives.jsonl")
    sql = """
        SELECT c.id, c.user_id, c.categorie[1] AS univers, c.period::text AS periode,
               c.privacy::text AS privacy, c.titre, c.creation, c.last_update, c.valide,
               c.tops
          FROM fives.catalog c
         WHERE c.categorie[1] = ANY(%s)
         ORDER BY c.id
    """
    with conn.cursor("cur_fives", row_factory=dict_row) as cur:
        cur.execute(sql, (list(UNIVERS),))
        for r in cur:
            univers, positions = r["univers"], []
            for rang, top in enumerate(r["tops"] or [], start=1):
                top = top if isinstance(top, dict) else {}
                brut = top.get("id")
                if brut is None or str(brut).strip() == "":
                    positions.append({"rang": rang, "statut": "vide"})
                    continue
                if not ENTIER.match(str(brut)):
                    positions.append({"rang": rang, "statut": "illisible",
                                      "id_brut": str(brut)})
                    recon.ecrire({"type": "position_illisible", "five_v1_id": r["id"],
                                  "univers": univers, "rang": rang, "id_brut": str(brut)})
                    continue
                v1_id = int(brut)
                res = resolution.get((univers, v1_id))
                if res is None:
                    positions.append({"rang": rang, "statut": "orpheline",
                                      "oeuvre_v1_id": v1_id})
                    recon.ecrire({"type": "position_orpheline", "five_v1_id": r["id"],
                                  "univers": univers, "rang": rang, "oeuvre_v1_id": v1_id,
                                  "titre_saisi": top.get("text")})
                    continue
                positions.append({
                    "rang": rang,
                    "oeuvre_v1_id": v1_id,
                    "canonique_v1_id": res["canonique"],
                    "id_tmdb": res["id_tmdb"],
                    "titre_saisi": top.get("text"),
                    "pourquoi": _pourquoi(pourquoi, consommes, r["id"], v1_id,
                                          res["canonique"], univers),
                    "commentaire": top.get("commentaire") or None,
                })
            marquer_doublons(positions, r["id"], univers, recon)
            sortie.ecrire({
                "v1_five_id": r["id"],
                "user_v1_id": r["user_id"],
                "univers": univers,
                "periode": r["periode"],
                "privacy_v1": r["privacy"],
                "titre": premier_texte(r["titre"]),
                "positions": positions,
                "dates": {"creation": r["creation"], "derniere_maj": r["last_update"]},
                "valide": r["valide"],
            })
    # Un « pourquoi » qui ne retrouve pas sa position, c'est un membre qui a
    # remanié son top sans que le texte suive. 2 675 cas sur 58 251 : ce n'est
    # pas une erreur d'export, c'est de la prose écrite par quelqu'un, et elle
    # sort plutôt que de disparaître en silence.
    for (five_id, id_catalog, univers), texte in pourquoi.items():
        if (five_id, id_catalog, univers) in consommes:
            continue
        recon.ecrire({"type": "pourquoi_orphelin", "five_v1_id": five_id,
                      "univers": univers, "oeuvre_v1_id": id_catalog, "pourquoi": texte})

    return {"fives.jsonl": sortie.fermer()}


def _pourquoi(index: dict, consommes: set, five_id: int, v1_id: int,
              canonique: int, univers: str) -> str | None:
    """Le texte du membre pour cette position — cité ou canonique, au choix.

    Il est rangé sous l'identifiant tel qu'il a été cité, sauf quand la fiche a
    été redirigée depuis : les deux clés sont donc essayées, et celle qui sert
    est marquée pour que le reliquat soit identifiable.
    """
    for cle in ((five_id, v1_id, univers), (five_id, canonique, univers)):
        if cle in index:
            consommes.add(cle)
            return index[cle]
    return None


def marquer_doublons(positions: list, five_id: int, univers: str, recon: Sortie) -> None:
    """Deux positions d'un même top qui désignent la même œuvre.

    Ça n'a rien d'exotique : 854 identifiants TMDB sont portés par plusieurs
    fiches V1 sans que `_301` les relie (côté films surtout), et la V1 laissait
    citer les deux. En V2 elles convergent sur un seul `oeuvre_id` — donc sur
    une seule arête, à un seul rang. On garde la meilleure position, on marque
    l'autre, et l'import n'a pas à deviner.
    """
    vues: dict = {}
    for p in positions:
        cle = (("tmdb", p["id_tmdb"]) if p.get("id_tmdb")
               else ("v1", p["canonique_v1_id"]) if p.get("canonique_v1_id") else None)
        if cle is None:
            continue
        if cle in vues:
            p["doublon_de"] = vues[cle]
            recon.ecrire({"type": "position_doublon", "five_v1_id": five_id,
                          "univers": univers, "rang": p["rang"],
                          "doublon_de_rang": vues[cle], "cle": list(cle)})
        else:
            vues[cle] = p["rang"]


# ----------------------------------------------------------------- le reste

def exporter_decouvertes(conn, dossier: Path, resolution: dict) -> dict:
    sortie = Sortie(dossier / "decouvertes.jsonl")
    with conn.cursor("cur_dec", row_factory=dict_row) as cur:
        cur.execute("""
            SELECT user_id, schemas AS univers, id AS oeuvre_v1_id, attribute,
                   creation, valide
              FROM public.users_decouverte
             WHERE schemas = ANY(%s)
             ORDER BY user_id, schemas, id
        """, (list(UNIVERS),))
        for r in cur:
            res = resolution.get((r["univers"], r["oeuvre_v1_id"])) or {}
            origine = next((a for a in (r["attribute"] or []) if isinstance(a, dict)), {})
            sortie.ecrire({
                "user_v1_id": r["user_id"],
                "univers": r["univers"],
                "oeuvre_v1_id": r["oeuvre_v1_id"],
                "canonique_v1_id": res.get("canonique"),
                "id_tmdb": res.get("id_tmdb"),
                "origine": origine or None,
                "creation": r["creation"],
                "valide": r["valide"],
            })
    return {"decouvertes.jsonl": sortie.fermer()}


def exporter_avis(conn, dossier: Path, resolution: dict) -> dict:
    sortie = Sortie(dossier / "avis.jsonl")
    with conn.cursor(row_factory=dict_row) as cur:
        for univers in UNIVERS:
            cur.execute(f"""
                SELECT id, id_catalog, user_id, titre, avis, note, creation, last_update,
                       valide, id_reponse
                  FROM {univers}.reviews ORDER BY id
            """)
            for r in cur.fetchall():
                res = resolution.get((univers, r["id_catalog"])) or {}
                sortie.ecrire({
                    "v1_avis_id": r["id"],
                    "user_v1_id": r["user_id"],
                    "univers": univers,
                    "oeuvre_v1_id": r["id_catalog"],
                    "canonique_v1_id": res.get("canonique"),
                    "id_tmdb": res.get("id_tmdb"),
                    "note": r["note"],
                    "titre": r["titre"],
                    "texte": r["avis"],
                    "reponse_a": r["id_reponse"],
                    "dates": {"creation": r["creation"], "derniere_maj": r["last_update"]},
                    "valide": r["valide"],
                })
    return {"avis.jsonl": sortie.fermer()}


# ----------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="Export de la base V1 vers des JSONL.")
    ap.add_argument("--dsn", default=os.environ.get("V1_DSN", DSN_DEFAUT))
    ap.add_argument("--out", required=True, type=Path,
                    help="répertoire de sortie (hors dépôt : il contient des emails)")
    ap.add_argument("--limite", type=int, default=None,
                    help="n'exporter que les N premiers utilisateurs (essai)")
    args = ap.parse_args()

    dossier: Path = args.out.expanduser()
    dossier.mkdir(parents=True, exist_ok=True)
    manifeste: dict[str, dict] = {}

    with psycopg.connect(args.dsn, row_factory=dict_row) as conn:
        conn.read_only = True
        recon = Sortie(dossier / "a-reconcilier.jsonl")

        with conn.cursor(row_factory=dict_row) as cur:
            cites = citations(cur)
            print(f"citations : {sum(cites.values()):>7} sur {len(cites)} fiches", file=sys.stderr)
            resolution, m = exporter_oeuvres(cur, dossier, cites, recon)
            manifeste |= m
            cur.execute("SELECT max(creation) AS m FROM fives.catalog")
            instantane = cur.fetchone()["m"]

        manifeste |= exporter_utilisateurs(conn, dossier, args.limite)
        manifeste |= exporter_fives(conn, dossier, resolution, recon)
        manifeste |= exporter_decouvertes(conn, dossier, resolution)
        manifeste |= exporter_avis(conn, dossier, resolution)
        manifeste |= exporter_secrets(conn, dossier)
        manifeste["a-reconcilier.jsonl"] = recon.fermer()

    manifest = {
        "exporte_le": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": psycopg.conninfo.conninfo_to_dict(args.dsn).get("dbname"),
        "instantane_v1": instantane.isoformat() if instantane else None,
        "univers": list(UNIVERS),
        "partiel": bool(args.limite),
        "fichiers": manifeste,
    }
    (dossier / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_defaut) + "\n",
        encoding="utf-8")

    largeur = max(len(n) for n in manifeste)
    for nom, info in manifeste.items():
        print(f"{nom:<{largeur}}  {info['lignes']:>7} lignes", file=sys.stderr)
    print(f"\n→ {dossier}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
