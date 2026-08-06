#!/usr/bin/env python3
"""
Étude — trois sources complémentaires : Wikidata, TVmaze, IMDb Datasets.

Ce qu'on cherche à savoir de chacune :
  Wikidata  -> pays, langues, relations, et les identifiants qui manquent
  TVmaze    -> dates, épisodes, calendriers de diffusion
  IMDb      -> notes, titres alternatifs, identifiants

Échantillon : l'export quotidien TMDB, stratifié par décile de popularité.
C'est un fichier public — aucune clé, aucun quota — donc l'étude tourne sans
dépendre ni de la base, ni du jeton TMDB (qui est refusé à l'heure où ceci est
écrit).

Aucune dépendance : stdlib seule, comme `etude_couverture_ar.py`.

Usage :
    python3 tools/etude_sources_complementaires.py [--n 10] [--out fichier.json]

`--n` est le nombre de séries **par décile** (10 par défaut, soit 100 séries).
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import statistics as st
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, timedelta

UA = {"User-Agent": "fivorites-v2-eval/0.1 (contact: mediashare@mediacamp.fr)"}

EXPORT_BASE = "http://files.tmdb.org/p/exports"
SPARQL = "https://query.wikidata.org/sparql"
TVMAZE = "https://api.tvmaze.com"
IMDB_RATINGS = "https://datasets.imdbws.com/title.ratings.tsv.gz"

# TVmaze annonce une vingtaine d'appels par tranche de 10 secondes. On reste
# nettement en dessous : l'étude n'est pas pressée et se faire bannir coûterait
# plus cher que d'attendre.
TVMAZE_PAUSE = 0.4
SPARQL_PAUSE = 1.2

ARABE = re.compile(r"[؀-ۿ]")
TURC = re.compile(r"[ğışĞİŞ]")


def get(url: str, *, raw: bool = False, retries: int = 2):
    """GET avec reprise. Renvoie None plutôt que de lever : une source
    indisponible est un résultat de l'étude, pas un plantage."""
    for essai in range(retries + 1):
        try:
            requete = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(requete, timeout=120) as reponse:
                blob = reponse.read()
            return blob if raw else json.loads(blob)
        except Exception as exc:  # noqa: BLE001 — on veut continuer, pas diagnostiquer
            if essai == retries:
                print(f"    ! {type(exc).__name__} sur {url[:90]}", file=sys.stderr)
            time.sleep(0.8)
    return None


# --------------------------------------------------------------- échantillon
def telecharger_export() -> tuple[date, list[dict]]:
    """Le dernier export disponible. TMDB le publie en milieu de matinée UTC,
    donc on remonte de quelques jours plutôt que de supposer celui du jour."""
    for recul in range(0, 5):
        jour = date.today() - timedelta(days=recul)
        url = f"{EXPORT_BASE}/tv_series_ids_{jour:%m_%d_%Y}.json.gz"
        blob = get(url, raw=True)
        if blob:
            lignes = gzip.decompress(blob).decode("utf-8").splitlines()
            series = [json.loads(ligne) for ligne in lignes if ligne.strip()]
            return jour, series
    raise SystemExit("aucun export TMDB téléchargeable")


def echantillon(series: list[dict], par_decile: int) -> list[dict]:
    """Stratification par décile de popularité.

    Un tirage uniforme donnerait presque uniquement du fond de catalogue — la
    falaise de popularité est telle que le premier décile couvre 406 à 3,71 et
    les neuf autres 3,71 à 0. Or c'est justement la variation par décile qu'on
    veut lire.
    """
    tries = sorted(series, key=lambda s: s.get("popularity", 0), reverse=True)
    taille = len(tries) // 10
    tire = []
    for decile in range(10):
        tranche = tries[decile * taille : (decile + 1) * taille]
        # Pas d'aléatoire : un pas régulier donne le même échantillon d'un run à
        # l'autre, donc deux mesures comparables.
        pas = max(1, len(tranche) // par_decile)
        for serie in tranche[::pas][:par_decile]:
            tire.append({**serie, "decile": decile + 1, "strate": "deciles"})
    return tire


def corpus(nom: str) -> str:
    if ARABE.search(nom or ""):
        return "arabe"
    if TURC.search(nom or ""):
        return "turc"
    return "autre"


def strate_corpus(series: list[dict], quel: str, combien: int) -> list[dict]:
    """Les `combien` séries les plus populaires d'un corpus donné.

    L'échantillon par décile n'en contient qu'une poignée — l'écriture arabe
    pèse 2,4 % du catalogue — et c'est justement là que les sources se
    comportent différemment. On tire donc une strate à part, depuis le même
    export : aucune clé d'API, aucun quota, et le corpus se lit sur le titre
    original.

    Comme dans l'étude arabophone, c'est le **meilleur cas** de chaque
    catalogue : les plus populaires, pas la moyenne.
    """
    retenus = [s for s in series if corpus(s.get("original_name", "")) == quel]
    retenus.sort(key=lambda s: s.get("popularity", 0), reverse=True)
    return [{**s, "decile": 0, "strate": quel} for s in retenus[:combien]]


# ----------------------------------------------------------------- Wikidata
REQUETE = """
SELECT ?tmdb ?item ?imdb ?tvmaze ?sitelinks
       (GROUP_CONCAT(DISTINCT ?paysCode; separator="|") AS ?pays)
       (GROUP_CONCAT(DISTINCT ?langueCode; separator="|") AS ?langues)
WHERE {
  VALUES ?tmdb { %s }
  ?item wdt:P4983 ?tmdb .
  OPTIONAL { ?item wdt:P345 ?imdb }
  OPTIONAL { ?item wdt:P8600 ?tvmaze }
  OPTIONAL { ?item wikibase:sitelinks ?sitelinks }
  OPTIONAL { ?item wdt:P495 ?paysItem . ?paysItem wdt:P297 ?paysCode }
  OPTIONAL { ?item wdt:P364 ?langueItem . ?langueItem wdt:P218 ?langueCode }
}
GROUP BY ?tmdb ?item ?imdb ?tvmaze ?sitelinks
"""


def wikidata(ids: list[int], lot: int = 100) -> dict[int, dict]:
    """id TMDB -> ce que Wikidata en sait. Entrée par P4983, pas par l'imdb_id :
    c'est le seul chemin disponible tant que `raw_source` est vide."""
    trouve: dict[int, dict] = {}
    for debut in range(0, len(ids), lot):
        valeurs = " ".join(f'"{i}"' for i in ids[debut : debut + lot])
        url = f"{SPARQL}?query={urllib.parse.quote(REQUETE % valeurs)}&format=json"
        reponse = get(url)
        if reponse:
            for ligne in reponse["results"]["bindings"]:
                def champ(nom: str) -> str:
                    return ligne.get(nom, {}).get("value", "")

                trouve[int(champ("tmdb"))] = {
                    "qid": champ("item").rsplit("/", 1)[-1],
                    "imdb": champ("imdb"),
                    "tvmaze": champ("tvmaze"),
                    "sitelinks": int(champ("sitelinks") or 0),
                    "pays": [p for p in champ("pays").split("|") if p],
                    "langues": [x for x in champ("langues").split("|") if x],
                }
        print(f"  wikidata {min(debut + lot, len(ids)):>4}/{len(ids)}")
        time.sleep(SPARQL_PAUSE)
    return trouve


def articles(qids: list[str], langues=("ar", "tr", "fr", "en"), lot: int = 50) -> dict[str, list]:
    """QID -> langues dans lesquelles un article existe."""
    trouve: dict[str, list] = {}
    for debut in range(0, len(qids), lot):
        paquet = "|".join(qids[debut : debut + lot])
        url = (
            "https://www.wikidata.org/w/api.php?action=wbgetentities"
            f"&ids={paquet}&props=sitelinks&format=json"
        )
        reponse = get(url)
        for qid, entite in (reponse or {}).get("entities", {}).items():
            liens = entite.get("sitelinks", {})
            trouve[qid] = [x for x in langues if f"{x}wiki" in liens]
        time.sleep(0.3)
    return trouve


# ------------------------------------------------------------------- TVmaze
def tvmaze(serie: dict, info_wd: dict) -> dict | None:
    """Une série TVmaze, avec ses épisodes.

    Deux entrées, dans cet ordre : l'identifiant quand Wikidata le donne, sinon
    la recherche par titre. La seconde est faillible — c'est justement ce qu'on
    mesure.
    """
    show = None
    voie = ""

    if info_wd.get("tvmaze"):
        show = get(f"{TVMAZE}/shows/{info_wd['tvmaze']}?embed=episodes")
        voie = "p8600"
        time.sleep(TVMAZE_PAUSE)

    if show is None and info_wd.get("imdb"):
        trouve = get(f"{TVMAZE}/lookup/shows?imdb={info_wd['imdb']}")
        time.sleep(TVMAZE_PAUSE)
        if trouve:
            show = get(f"{TVMAZE}/shows/{trouve['id']}?embed=episodes")
            voie = "imdb"
            time.sleep(TVMAZE_PAUSE)

    if show is None and serie.get("original_name"):
        requete = urllib.parse.quote(serie["original_name"])
        resultats = get(f"{TVMAZE}/search/shows?q={requete}")
        time.sleep(TVMAZE_PAUSE)
        # Le score de TVmaze est un score de pertinence textuelle, pas une
        # preuve d'identité. Au-dessous de 0,9 l'appariement est trop souvent un
        # homonyme : on préfère compter un échec qu'un faux positif.
        if resultats and resultats[0].get("score", 0) >= 0.9:
            show = get(f"{TVMAZE}/shows/{resultats[0]['show']['id']}?embed=episodes")
            voie = "titre"
            time.sleep(TVMAZE_PAUSE)

    if not show:
        return None

    episodes = (show.get("_embedded") or {}).get("episodes") or []
    diffusion = show.get("schedule") or {}
    return {
        "voie": voie,
        "premiered": show.get("premiered"),
        "ended": show.get("ended"),
        "status": show.get("status"),
        "network": (show.get("network") or show.get("webChannel") or {}).get("name"),
        "pays": ((show.get("network") or {}).get("country") or {}).get("code"),
        "calendrier": bool(diffusion.get("days")),
        "episodes": len(episodes),
        "episodes_dates": sum(1 for e in episodes if e.get("airdate")),
        "episodes_resumes": sum(1 for e in episodes if e.get("summary")),
        "resume_car": sum(len(e.get("summary") or "") for e in episodes),
    }


# --------------------------------------------------------------------- IMDb
def notes_imdb() -> dict[str, tuple[float, int]]:
    """title.ratings — le seul des sept fichiers assez petit pour être chargé
    tel quel (~8 Mo compressés). title.akas, qui porterait les titres
    alternatifs, en fait plus de 300 : hors périmètre de cette étude."""
    blob = get(IMDB_RATINGS, raw=True)
    if not blob:
        return {}
    notes = {}
    lignes = gzip.decompress(blob).decode("utf-8").splitlines()
    for ligne in lignes[1:]:
        tconst, note, votes = ligne.split("\t")
        notes[tconst] = (float(note), int(votes))
    return notes


# ------------------------------------------------------------------ rapport
def part(compte: int, total: int) -> str:
    return f"{compte:>4}  {100 * compte / total:5.1f} %" if total else "   0      – "


def tableau(titre: str, lignes: list[tuple[str, int, int]]) -> None:
    print(f"\n{titre}")
    print("-" * len(titre))
    for libelle, compte, total in lignes:
        print(f"  {libelle:<34} {part(compte, total)}")


def main() -> None:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--n", type=int, default=10, help="séries par décile")
    parseur.add_argument("--corpus", type=int, default=40, help="séries par corpus arabe/turc")
    parseur.add_argument("--out", default="etude_sources_complementaires.json")
    options = parseur.parse_args()

    jour, tout = telecharger_export()
    print(f"export du {jour} — {len(tout):,} séries".replace(",", " "))

    tire = echantillon(tout, options.n)
    tire += strate_corpus(tout, "arabe", options.corpus)
    tire += strate_corpus(tout, "turc", options.corpus)
    print(
        f"échantillon : {len(tire)} séries "
        f"({options.n}/décile + {options.corpus} arabes + {options.corpus} turques)"
    )

    print("\nWikidata…")
    info = wikidata([s["id"] for s in tire])
    qids = [v["qid"] for v in info.values() if v["qid"]]
    par_langue = articles(qids)

    print("\nIMDb (title.ratings)…")
    notes = notes_imdb()
    print(f"  {len(notes):,} titres notés".replace(",", " "))

    print("\nTVmaze…")
    resultats = []
    for rang, serie in enumerate(tire, 1):
        wd = info.get(serie["id"], {})
        tv = tvmaze(serie, wd)
        imdb = wd.get("imdb", "")
        resultats.append(
            {
                "id": serie["id"],
                "nom": serie.get("original_name"),
                "decile": serie["decile"],
                "strate": serie["strate"],
                "corpus": corpus(serie.get("original_name", "")),
                "popularite": serie.get("popularity"),
                "wikidata": wd or None,
                "articles": par_langue.get(wd.get("qid", ""), []),
                "imdb_note": notes.get(imdb),
                "tvmaze": tv,
            }
        )
        if rang % 10 == 0:
            print(f"  {rang}/{len(tire)}")

    total = len(resultats)
    avec_wd = [r for r in resultats if r["wikidata"]]
    avec_imdb = [r for r in avec_wd if r["wikidata"]["imdb"]]
    avec_tv = [r for r in resultats if r["tvmaze"]]

    tableau(
        "Wikidata — le raccordement",
        [
            ("item trouvé (P4983)", len(avec_wd), total),
            ("dont identifiant IMDb", len(avec_imdb), total),
            ("dont identifiant TVmaze (P8600)", sum(1 for r in avec_wd if r["wikidata"]["tvmaze"]), total),
            ("pays d'origine", sum(1 for r in avec_wd if r["wikidata"]["pays"]), total),
            ("langue originale", sum(1 for r in avec_wd if r["wikidata"]["langues"]), total),
            ("article arabe", sum(1 for r in resultats if "ar" in r["articles"]), total),
            ("article turc", sum(1 for r in resultats if "tr" in r["articles"]), total),
            ("article français", sum(1 for r in resultats if "fr" in r["articles"]), total),
            ("article anglais", sum(1 for r in resultats if "en" in r["articles"]), total),
        ],
    )

    voies = Counter(r["tvmaze"]["voie"] for r in avec_tv)
    tableau(
        "TVmaze — dates, épisodes, calendrier",
        [
            ("série trouvée", len(avec_tv), total),
            ("  par identifiant Wikidata", voies["p8600"], total),
            ("  par identifiant IMDb", voies["imdb"], total),
            ("  par titre (appariement)", voies["titre"], total),
            ("date de première diffusion", sum(1 for r in avec_tv if r["tvmaze"]["premiered"]), total),
            ("diffuseur", sum(1 for r in avec_tv if r["tvmaze"]["network"]), total),
            ("calendrier de diffusion", sum(1 for r in avec_tv if r["tvmaze"]["calendrier"]), total),
            ("au moins un épisode", sum(1 for r in avec_tv if r["tvmaze"]["episodes"]), total),
            ("résumés d'épisode", sum(1 for r in avec_tv if r["tvmaze"]["episodes_resumes"]), total),
        ],
    )

    tableau(
        "IMDb Datasets — les notes",
        [
            ("note disponible", sum(1 for r in resultats if r["imdb_note"]), total),
            ("note sur les séries raccordées", sum(1 for r in avec_imdb if r["imdb_note"]), len(avec_imdb)),
        ],
    )

    print("\nPar décile — item Wikidata / série TVmaze")
    print("-" * 42)
    par_decile = defaultdict(lambda: [0, 0, 0])
    for r in (x for x in resultats if x["strate"] == "deciles"):
        case = par_decile[r["decile"]]
        case[0] += 1
        case[1] += bool(r["wikidata"])
        case[2] += bool(r["tvmaze"])
    for decile in sorted(par_decile):
        n, wd, tv = par_decile[decile]
        print(f"  décile {decile:>2}   wikidata {100 * wd / n:5.1f} %   tvmaze {100 * tv / n:5.1f} %")

    print("\nPar strate — ce que chaque source rattrape")
    print("-" * 78)
    print(f"  {'strate':<10}{'séries':>8}{'wikidata':>11}{'imdb':>9}{'tvmaze':>9}"
          f"{'art. ar':>10}{'épisodes':>11}")
    for nom in ("deciles", "arabe", "turc"):
        lot = [r for r in resultats if r["strate"] == nom]
        if not lot:
            continue
        n = len(lot)
        wd = sum(1 for r in lot if r["wikidata"])
        im = sum(1 for r in lot if (r["wikidata"] or {}).get("imdb"))
        tv = sum(1 for r in lot if r["tvmaze"])
        ar = sum(1 for r in lot if "ar" in r["articles"])
        ep = sum(1 for r in lot if r["tvmaze"] and r["tvmaze"]["episodes_resumes"])
        print(
            f"  {nom:<10}{n:>8}{100 * wd / n:>10.1f}%{100 * im / n:>8.1f}%"
            f"{100 * tv / n:>8.1f}%{100 * ar / n:>9.1f}%{100 * ep / n:>10.1f}%"
        )

    resumes = [r["tvmaze"]["resume_car"] for r in avec_tv if r["tvmaze"]["resume_car"]]
    if resumes:
        print(
            f"\nMatière TVmaze (résumés d'épisode cumulés) : "
            f"médiane {int(st.median(resumes)):,} car., moyenne {int(st.mean(resumes)):,} car.".replace(
                ",", " "
            )
        )

    with open(options.out, "w", encoding="utf-8") as fichier:
        json.dump(
            {"export": str(jour), "n_par_decile": options.n, "series": resultats},
            fichier,
            ensure_ascii=False,
            indent=1,
        )
    print(f"\nDonnées brutes : {options.out}")


if __name__ == "__main__":
    main()
