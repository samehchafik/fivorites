#!/usr/bin/env python3
"""
Étude de couverture — l'univers livre : Open Library, Wikidata, UNESCO, BnF.

Il n'existe pas de TMDB du livre. Le candidat pivot est Open Library
(modèle work/édition, API libre, dumps mensuels) ; cette étude mesure ce
qu'il vaut vraiment sur les quatre langues cibles — français, anglais,
espagnol, arabe — et ce que les sources complémentaires rattrapent.

Quatre volets :
  1. Raccordement       -> l'œuvre Wikidata se relie-t-elle à Open Library ?
  2. Traductions        -> qui les trouve : OL, Wikidata (P629), UNESCO ?
  3. Matière à notation -> peut-on noter les 6 axes ? (protocole de
                           l'étude arabe : texte cumulé >= 2 000 car.)
  4. Procurabilité      -> ISBN par langue cible, présence BnF

Échantillon : les N œuvres littéraires les plus « connues » de chaque langue
originale (P31 œuvre littéraire/roman, tri par nombre de sitelinks — le seul
proxy de popularité gratuit, faute d'un export TMDB). C'est donc le
**meilleur cas** de chaque corpus, comme dans l'étude arabe des séries.

Sources : Wikidata SPARQL, Open Library, UNESCO DataHub (Index
Translationum, 829 k notices), BnF SRU, Wikipédia. Toutes gratuites, sans
clé. Google Books est écarté du protocole : son quota anonyme partagé
répond 429 en permanence — une clé serait nécessaire.

Aucune dépendance : stdlib seule, comme `etude_couverture_ar.py`.

Usage : python3 tools/etude_couverture_livres.py [--n 30] [--out fichier.json]

`--n` est le nombre d'œuvres **par langue** (30 par défaut, soit 120 œuvres).
"""
import argparse
import json
import statistics as st
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter

UA = {"User-Agent": "fivorites-v2-eval/0.1 (contact: mediashare@mediacamp.fr)"}
SPARQL = "https://query.wikidata.org/sparql"
UNESCO = "https://data.unesco.org/api/explore/v2.1/catalog/datasets/tran001/records"
BNF = "http://catalogue.bnf.fr/api/SRU"

# Les quatre corpus : code ISO -> (QID de la langue, code MARC d'Open Library)
LANGUES = {
    "fr": ("Q150", "fre"),
    "en": ("Q1860", "eng"),
    "es": ("Q1321", "spa"),
    "ar": ("Q13955", "ara"),
}
CIBLES = ["fr", "en", "es", "ar"]
MARC_VERS_ISO = {marc: iso for iso, (_, marc) in LANGUES.items()}

# Le critère de notabilité de l'étude arabe, réutilisé tel quel : en dessous,
# pas assez de matière pour espérer une notation fiable des 6 axes.
NOTABLE_CAR = 2000


def get(url, retries=2, binaire=False):
    for k in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45) as r:
                data = r.read()
                return data if binaire else json.loads(data)
        except Exception as e:
            if k == retries:
                print(f"  !! {e} — {url[:110]}", file=sys.stderr)
                return None
            time.sleep(2.5 * (k + 1))


def sparql(query):
    return get(f"{SPARQL}?query={urllib.parse.quote(query)}&format=json")


# ── Volet 0 : les corpus ────────────────────────────────────────────────────

def corpus(iso, qlang, n):
    """Les n œuvres littéraires de langue originale `iso` au plus de sitelinks,
    avec l'OLID (P648) et les titres Wikipédia des quatre langues cibles."""
    wikis = "\n".join(
        f'OPTIONAL {{ ?a_{l} schema:about ?w ; '
        f'schema:isPartOf <https://{l}.wikipedia.org/> ; schema:name ?t_{l} }}'
        for l in CIBLES
    )
    # La sélection est isolée dans une sous-requête : jointe aux OPTIONAL et au
    # service d'étiquettes, la version à plat dépasse le délai de WDQS sur le
    # corpus anglais (502 mesuré au premier essai).
    q = f"""
    SELECT ?w ?wLabel ?auteurLabel ?sitelinks ?olid ?t_fr ?t_en ?t_es ?t_ar WHERE {{
      {{ SELECT DISTINCT ?w ?sitelinks WHERE {{
           VALUES ?type {{ wd:Q7725634 wd:Q8261 }}
           ?w wdt:P31 ?type ; wdt:P407 wd:{qlang} ; wikibase:sitelinks ?sitelinks .
           FILTER(?sitelinks >= 5)
         }} ORDER BY DESC(?sitelinks) LIMIT {n * 2} }}
      OPTIONAL {{ ?w wdt:P648 ?olid }}
      OPTIONAL {{ ?w wdt:P50 ?auteur }}
      {wikis}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{iso},en". }}
    }}
    ORDER BY DESC(?sitelinks)
    """
    r = sparql(q)
    if not r:
        return []
    vus, out = set(), []
    for b in r["results"]["bindings"]:
        def v(nom):
            return b.get(nom, {}).get("value")
        qid = v("w").split("/")[-1]
        if qid in vus:
            continue  # doublons des VALUES / auteurs multiples
        vus.add(qid)
        out.append(dict(
            qid=qid, titre=v("wLabel"), auteur=v("auteurLabel"),
            sitelinks=int(v("sitelinks")), olid=v("olid"),
            wp={l: v(f"t_{l}") for l in CIBLES if v(f"t_{l}")},
        ))
        if len(out) >= n:
            break
    return out


def editions_wikidata(qids):
    """QID -> (nb d'éditions P629, langues de ces éditions). La couverture
    édition de Wikidata est réputée mince ; c'est ce qu'on vérifie."""
    out = {q: (0, set()) for q in qids}
    values = " ".join(f"wd:{q}" for q in qids)
    q = f"""
    SELECT ?w ?ed ?code WHERE {{
      VALUES ?w {{ {values} }}
      ?ed wdt:P629 ?w .
      OPTIONAL {{ ?ed wdt:P407 ?l . ?l wdt:P218 ?code }}
    }}
    """
    r = sparql(q)
    if not r:
        return out
    par_oeuvre = {}
    for b in r["results"]["bindings"]:
        qid = b["w"]["value"].split("/")[-1]
        ed = b["ed"]["value"]
        code = b.get("code", {}).get("value")
        par_oeuvre.setdefault(qid, {}).setdefault(ed, set())
        if code:
            par_oeuvre[qid][ed].add(code)
    for qid, eds in par_oeuvre.items():
        langues = set()
        for codes in eds.values():
            langues |= codes
        out[qid] = (len(eds), langues)
    return out


# ── Volet 1+2 : Open Library ────────────────────────────────────────────────

def ol_resoudre(oeuvre):
    """(olid, voie) — P648 d'abord, sinon recherche titre+auteur, puis titre.
    C'est le protocole série transposé : identifiant pour décider, titre pour
    chercher."""
    if oeuvre["olid"]:
        return oeuvre["olid"], "p648"
    base = "https://openlibrary.org/search.json?limit=3&fields=key,title,edition_count"
    t = urllib.parse.quote(oeuvre["titre"] or "")
    if oeuvre["auteur"]:
        r = get(f"{base}&title={t}&author={urllib.parse.quote(oeuvre['auteur'])}")
        if r and r.get("docs"):
            return r["docs"][0]["key"].split("/")[-1], "titre+auteur"
    r = get(f"{base}&title={t}")
    if r and r.get("docs"):
        return r["docs"][0]["key"].split("/")[-1], "titre"
    return None, None


def ol_oeuvre(olid):
    """Description du work + inventaire des éditions : langues, ISBN."""
    w = get(f"https://openlibrary.org/works/{olid}.json") or {}
    if (w.get("type") or {}).get("key") == "/type/redirect":
        # Work fusionné : P648 pointe sur l'ancien identifiant, dont la page
        # d'éditions répond 404. On suit la redirection.
        olid = w.get("location", "").split("/")[-1] or olid
        w = get(f"https://openlibrary.org/works/{olid}.json") or {}
    desc = w.get("description") or ""
    if isinstance(desc, dict):
        desc = desc.get("value", "")
    eds = get(f"https://openlibrary.org/works/{olid}/editions.json?limit=500") or {}
    langues, sans_langue, isbn_par_langue, nb = Counter(), 0, {}, 0
    for e in eds.get("entries", []):
        nb += 1
        codes = [l["key"].split("/")[-1] for l in e.get("languages") or []]
        if not codes:
            sans_langue += 1
        isbns = (e.get("isbn_13") or []) + (e.get("isbn_10") or [])
        for c in codes:
            langues[c] += 1
            iso = MARC_VERS_ISO.get(c)
            if iso and isbns and iso not in isbn_par_langue:
                isbn_par_langue[iso] = isbns[0]
    return dict(
        description=len(desc), editions=nb, sans_langue=sans_langue,
        langues=dict(langues), isbn_par_langue=isbn_par_langue,
    )


# ── Volet 2 : UNESCO Index Translationum ────────────────────────────────────

def unesco(titre):
    """Notices de l'Index (1978-2008) portant ce titre original : nombre de
    notices, traductions cumulées, langues cibles touchées."""
    t = titre.replace('"', " ")
    clause = 'search(original_title, "%s")' % t
    u = f"{UNESCO}?limit=20&where={urllib.parse.quote(clause)}"
    r = get(u)
    if not r:
        return dict(notices=0, traductions=0, langues=[])
    langues, total = set(), 0
    for rec in r.get("results", []):
        total += rec.get("translations_count") or 0
        try:
            for tr in json.loads((rec.get("translations") or "[]").replace("'", '"')):
                if tr.get("translated_title_language"):
                    langues.add(tr["translated_title_language"])
        except Exception:
            pass  # le champ est un repr Python, pas du JSON — best effort
    return dict(notices=r.get("total_count", 0), traductions=total,
                langues=sorted(langues))


# ── Volet 3 : Wikipédia ─────────────────────────────────────────────────────

def extract_len(lang, title):
    w = get(f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=extracts"
            f"&explaintext=1&titles={urllib.parse.quote(title)}&format=json&redirects=1")
    try:
        return len(list(w["query"]["pages"].values())[0].get("extract", "") or "")
    except Exception:
        return 0


# ── Volet 4 : BnF ───────────────────────────────────────────────────────────

def bnf(titre):
    """Nombre de notices du catalogue général pour ce titre. Le référentiel
    français de l'œuvre *et* de ses traductions vers le français."""
    q = urllib.parse.quote(f'bib.title all "{titre}"')
    xml = get(f"{BNF}?version=1.2&operation=searchRetrieve&query={q}&maximumRecords=1",
              binaire=True)
    if not xml:
        return 0
    try:
        racine = ET.fromstring(xml)
        n = racine.find(".//{http://www.loc.gov/zing/srw/}numberOfRecords")
        return int(n.text) if n is not None else 0
    except Exception:
        return 0


# ── L'étude ─────────────────────────────────────────────────────────────────

def etudier(iso, n):
    qlang, _ = LANGUES[iso]
    print(f"\n[{iso}] corpus Wikidata…", flush=True)
    base = corpus(iso, qlang, n)
    print(f"[{iso}] {len(base)} œuvres. Éditions P629…", flush=True)
    p629 = editions_wikidata([o["qid"] for o in base])
    for i, o in enumerate(base):
        nb, langs = p629.get(o["qid"], (0, set()))
        o["wd_editions"], o["wd_editions_langues"] = nb, sorted(langs)

        olid, voie = ol_resoudre(o)
        o["ol_olid"], o["ol_voie"] = olid, voie
        o["ol"] = ol_oeuvre(olid) if olid else None
        time.sleep(0.2)

        o["unesco"] = unesco(o["titre"] or "")
        titre_fr = o["wp"].get("fr") or o["titre"] or ""
        o["bnf"] = bnf(titre_fr)

        o["wp_car"] = {l: extract_len(l, t) for l, t in o["wp"].items()}
        cumul = sum(o["wp_car"].values()) + (o["ol"] or {}).get("description", 0)
        o["notable"] = cumul >= NOTABLE_CAR
        if (i + 1) % 10 == 0:
            print(f"   … {i + 1}/{len(base)}", flush=True)
        time.sleep(0.2)
    return base


def pct(part, total):
    return f"{100 * part / (total or 1):.0f} %"


def tableau(corpus_par_langue):
    lignes = [
        ("Œuvres du corpus", lambda L: str(len(L))),
        ("— Volet 1 · raccordement Open Library —", None),
        ("OLID direct (P648)", lambda L: pct(sum(1 for o in L if o["ol_voie"] == "p648"), len(L))),
        ("résolu par recherche", lambda L: pct(sum(1 for o in L if o["ol_voie"] in ("titre+auteur", "titre")), len(L))),
        ("non raccordable", lambda L: pct(sum(1 for o in L if not o["ol_olid"]), len(L))),
        ("— Volet 2 · traductions —", None),
        ("éditions OL, médiane", lambda L: str(int(st.median([o["ol"]["editions"] for o in L if o["ol"]] or [0])))),
        ("éditions OL sans langue", lambda L: pct(sum(o["ol"]["sans_langue"] for o in L if o["ol"]),
                                                  sum(o["ol"]["editions"] for o in L if o["ol"]))),
        ("langues OL, médiane", lambda L: str(int(st.median([len(o["ol"]["langues"]) for o in L if o["ol"]] or [0])))),
        ("édition fr dans OL", lambda L: pct(sum(1 for o in L if o["ol"] and o["ol"]["langues"].get("fre")), len(L))),
        ("édition en dans OL", lambda L: pct(sum(1 for o in L if o["ol"] and o["ol"]["langues"].get("eng")), len(L))),
        ("édition es dans OL", lambda L: pct(sum(1 for o in L if o["ol"] and o["ol"]["langues"].get("spa")), len(L))),
        ("édition ar dans OL", lambda L: pct(sum(1 for o in L if o["ol"] and o["ol"]["langues"].get("ara")), len(L))),
        ("œuvres avec P629 (Wikidata)", lambda L: pct(sum(1 for o in L if o["wd_editions"]), len(L))),
        ("trouvée dans l'Index UNESCO", lambda L: pct(sum(1 for o in L if o["unesco"]["notices"]), len(L))),
        ("traductions UNESCO, médiane", lambda L: str(int(st.median([o["unesco"]["traductions"] for o in L] or [0])))),
        ("— Volet 3 · matière à notation —", None),
        ("article Wikipédia fr", lambda L: pct(sum(1 for o in L if o["wp_car"].get("fr", 0) > 0), len(L))),
        ("article Wikipédia ar", lambda L: pct(sum(1 for o in L if o["wp_car"].get("ar", 0) > 0), len(L))),
        ("longueur wp langue d'origine", lambda L: str(int(st.median([o["wp_car"].get(iso_de(L), 0) for o in L] or [0])))),
        ("description OL, médiane", lambda L: str(int(st.median([o["ol"]["description"] for o in L if o["ol"]] or [0])))),
        ("notable (>= 2 000 car.)", lambda L: pct(sum(1 for o in L if o["notable"]), len(L))),
        ("— Volet 4 · procurabilité —", None),
        ("ISBN d'une édition fr", lambda L: pct(sum(1 for o in L if o["ol"] and "fr" in o["ol"]["isbn_par_langue"]), len(L))),
        ("ISBN d'une édition ar", lambda L: pct(sum(1 for o in L if o["ol"] and "ar" in o["ol"]["isbn_par_langue"]), len(L))),
        ("présente à la BnF", lambda L: pct(sum(1 for o in L if o["bnf"]), len(L))),
    ]
    isos = list(corpus_par_langue)
    larg = max(len(t) for t, _ in lignes) + 2
    print("\n" + " " * larg + "  ".join(f"{i:>8}" for i in isos))
    for titre, f in lignes:
        if f is None:
            print(titre)
            continue
        vals = "  ".join(f"{f(corpus_par_langue[i]):>8}" for i in isos)
        print(f"{titre:<{larg}}{vals}")


def iso_de(L):
    return L[0]["_iso"] if L else "en"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=30, help="œuvres par langue")
    p.add_argument("--out", default="etude_couverture_livres.json")
    args = p.parse_args()

    resultats = {}
    for iso in LANGUES:
        L = etudier(iso, args.n)
        for o in L:
            o["_iso"] = iso
        resultats[iso] = L

    tableau(resultats)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(resultats, f, ensure_ascii=False, indent=1)
    print(f"\nDonnées brutes : {args.out}")


if __name__ == "__main__":
    main()
