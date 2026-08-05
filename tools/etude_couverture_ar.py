#!/usr/bin/env python3
"""
Étude de couverture — catalogue arabophone / turc vs occidental.

Trois volets :
  1. Couverture texte      -> peut-on noter les 6 axes de goût ?
  2. Disponibilité visuelle -> le swipe est-il jouable ?
  3. Proxys SEO arabe       -> pages vues Wikipédia + suggestions Google

Sources : TMDB (clé V1), Wikidata SPARQL (P345 via imdb_id), Wikipédia REST.
Sortie  : JSON brut + tableaux console.

Usage : python3 tools/etude_couverture_ar.py [--n 200]
"""
import json, sys, time, urllib.request, urllib.parse, statistics as st
from collections import Counter

TMDB_KEY = "b2788d431e93532f095b33ea23721262"
UA = {"User-Agent": "fivorites-v2-eval/0.1 (contact: mediashare@mediacamp.fr)"}
N = 200
if "--n" in sys.argv:
    N = int(sys.argv[sys.argv.index("--n") + 1])


def get(url, retries=2):
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception:
            time.sleep(0.6)
    return None


# ---------------------------------------------------------------- 1. échantillons
def discover(params, n):
    """Récupère les n séries les plus populaires correspondant aux critères."""
    out, page = [], 1
    while len(out) < n and page <= 25:
        d = get(f"https://api.themoviedb.org/3/discover/tv?api_key={TMDB_KEY}"
                f"&{params}&sort_by=popularity.desc&page={page}")
        if not d or not d.get("results"):
            break
        out += d["results"]
        page += 1
    return out[:n]


def details(tid):
    return get(f"https://api.themoviedb.org/3/tv/{tid}?api_key={TMDB_KEY}"
               f"&append_to_response=images,translations,external_ids,keywords"
               f"&include_image_language=ar,fr,en,null")


# ---------------------------------------------------------------- 2. wikidata / wikipédia
def resolve_wikidata(imdb_ids):
    """imdb_id -> QID, par lots (P345). Bien plus fiable que le wikidata_id de TMDB."""
    mapping = {}
    ids = [i for i in imdb_ids if i]
    for k in range(0, len(ids), 50):
        lot = ids[k:k + 50]
        values = " ".join(f'"{i}"' for i in lot)
        q = f'SELECT ?item ?imdb WHERE {{ VALUES ?imdb {{ {values} }} ?item wdt:P345 ?imdb. }}'
        r = get(f"https://query.wikidata.org/sparql?query={urllib.parse.quote(q)}&format=json")
        if r:
            for b in r["results"]["bindings"]:
                mapping[b["imdb"]["value"]] = b["item"]["value"].split("/")[-1]
        time.sleep(1.2)
    return mapping


def sitelinks(qids):
    """QID -> {langue: titre} pour ar/fr/en, par lots de 50."""
    out = {}
    qids = list(qids)
    for k in range(0, len(qids), 50):
        lot = "|".join(qids[k:k + 50])
        e = get("https://www.wikidata.org/w/api.php?action=wbgetentities"
                f"&ids={lot}&props=sitelinks&format=json")
        if not e:
            continue
        for qid, ent in e.get("entities", {}).items():
            sl = ent.get("sitelinks", {})
            out[qid] = {w[:-4]: sl[w]["title"] for w in ("arwiki", "frwiki", "enwiki") if w in sl}
        time.sleep(0.4)
    return out


def extract_len(lang, title):
    w = get(f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=extracts"
            f"&explaintext=1&titles={urllib.parse.quote(title)}&format=json&redirects=1")
    try:
        return len(list(w["query"]["pages"].values())[0].get("extract", "") or "")
    except Exception:
        return 0


def pageviews(lang, title, jours=60):
    """Pages vues Wikipédia — proxy d'intérêt du public, à défaut de volume Google."""
    t = urllib.parse.quote(title.replace(" ", "_"), safe="")
    u = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
         f"{lang}.wikipedia/all-access/user/{t}/monthly/2025080100/2026080100")
    d = get(u)
    if not d or "items" not in d:
        return 0
    vals = [i["views"] for i in d["items"]]
    return round(st.mean(vals)) if vals else 0


# ---------------------------------------------------------------- 3. mesure d'un corpus
def mesurer(label, params, n):
    print(f"\n[{label}] collecte de {n} séries…", flush=True)
    base = discover(params, n)
    lignes = []
    for i, r in enumerate(base):
        d = details(r["id"])
        if not d:
            continue
        img = d.get("images", {})
        tr = d.get("translations", {}).get("translations", [])
        ov = {t["iso_639_1"]: len(t["data"].get("overview") or "") for t in tr}
        lignes.append(dict(
            id=r["id"], nom=d.get("original_name") or d.get("name") or "",
            pop=round(d.get("popularity", 0), 1), votes=d.get("vote_count", 0),
            pays=(d.get("origin_country") or [None])[0],
            affiches=len(img.get("posters", [])), fonds=len(img.get("backdrops", [])),
            logos=len(img.get("logos", [])),
            trad=sum(1 for v in ov.values() if v > 0),
            txt_total=sum(ov.values()),
            ov_ar=ov.get("ar", 0), ov_en=ov.get("en", 0), ov_fr=ov.get("fr", 0),
            kw=len(d.get("keywords", {}).get("results", [])),
            saisons=d.get("number_of_seasons", 0), episodes=d.get("number_of_episodes", 0),
            imdb=d.get("external_ids", {}).get("imdb_id"),
        ))
        if (i + 1) % 25 == 0:
            print(f"   … {i+1}/{len(base)}", flush=True)

    print(f"[{label}] résolution Wikidata (P345)…", flush=True)
    qmap = resolve_wikidata([l["imdb"] for l in lignes])
    slmap = sitelinks(set(qmap.values()))
    print(f"[{label}] extraction Wikipédia…", flush=True)
    for l in lignes:
        q = qmap.get(l["imdb"] or "")
        sl = slmap.get(q, {}) if q else {}
        l["qid"] = q
        for lg in ("ar", "fr", "en"):
            l[f"wp_{lg}"] = extract_len(lg, sl[lg]) if lg in sl else 0
        l["wp_ar_titre"] = sl.get("ar")
    return lignes


def resume(label, L):
    n = len(L) or 1
    def moy(k): return round(sum(x[k] for x in L) / n, 1)
    def pct(f): return round(100 * sum(1 for x in L if f(x)) / n)
    def med(k): return round(st.median([x[k] for x in L]))
    return dict(
        corpus=label, n=n,
        affiches_moy=moy("affiches"), affiches_med=med("affiches"),
        pct_0_affiche=pct(lambda x: x["affiches"] == 0),
        pct_3plus_affiches=pct(lambda x: x["affiches"] >= 3),
        fonds_moy=moy("fonds"), pct_0_fond=pct(lambda x: x["fonds"] == 0),
        txt_moy=moy("txt_total"), txt_med=med("txt_total"),
        ov_ar_moy=moy("ov_ar"), pct_ov_ar=pct(lambda x: x["ov_ar"] > 0),
        ov_en_moy=moy("ov_en"), pct_ov_en=pct(lambda x: x["ov_en"] > 0),
        trad_moy=moy("trad"), kw_moy=moy("kw"),
        pct_wikidata=pct(lambda x: x["qid"]),
        pct_wp_ar=pct(lambda x: x["wp_ar"] > 0), wp_ar_moy=moy("wp_ar"),
        pct_wp_en=pct(lambda x: x["wp_en"] > 0), wp_en_moy=moy("wp_en"),
        pct_notable=pct(lambda x: (x["txt_total"] + x["wp_ar"] + x["wp_en"]) >= 2000),
        pct_swipable=pct(lambda x: x["affiches"] >= 1 and x["fonds"] >= 1),
    )


def google_suggest(seed, hl, gl):
    u = ("https://suggestqueries.google.com/complete/search?client=firefox"
         f"&hl={hl}&gl={gl}&q={urllib.parse.quote(seed)}")
    try:
        req = urllib.request.Request(u, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8", "replace"))[1]
    except Exception:
        return []


if __name__ == "__main__":
    corpus = {
        "arabophone": "with_original_language=ar",
        "golfe":      "with_origin_country=SA|AE|KW|QA|BH|OM",
        "turc":       "with_original_language=tr",
        "occidental": "with_original_language=en",
    }
    res, brut = {}, {}
    for label, params in corpus.items():
        L = mesurer(label, params, N)
        brut[label] = L
        res[label] = resume(label, L)

    json.dump({"resume": res, "brut": brut}, open("etude_couverture_ar.json", "w"),
              ensure_ascii=False, indent=1)

    cols = ["n", "pct_swipable", "affiches_moy", "affiches_med", "pct_0_affiche", "fonds_moy",
            "txt_moy", "txt_med", "pct_ov_ar", "ov_ar_moy", "trad_moy", "kw_moy",
            "pct_wikidata", "pct_wp_ar", "wp_ar_moy", "pct_wp_en", "wp_en_moy", "pct_notable"]
    print("\n" + "=" * 100)
    print(f"{'indicateur':22}" + "".join(f"{c:>13}" for c in corpus))
    for c in cols:
        print(f"{c:22}" + "".join(f"{res[k][c]:>13}" for k in corpus))
    print("=" * 100)
    print("\nÉcrit dans etude_couverture_ar.json")
