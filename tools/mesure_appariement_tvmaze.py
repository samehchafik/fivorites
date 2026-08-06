#!/usr/bin/env python3
"""Précision de l'appariement TVmaze par titre, contre la vérité terrain P8600.

Pour chaque série dont Wikidata donne l'id TVmaze (paire vérifiée par des
humains), on rejoue la recherche par titre et on regarde :
  - le bon id sort-il en tête ? à quel rang ?
  - le seuil score >= 0.9 aurait-il accepté un mauvais candidat ?
  - l'égalité externals.imdb (présente dans la réponse de recherche, gratuite)
    aurait-elle confirmé le bon / rejeté le mauvais ?
"""
import json, sys, time, urllib.parse, urllib.request

UA = {"User-Agent": "fivorites-v2-eval/0.1 (contact: mediashare@mediacamp.fr)"}

def get(url, retries=2):
    for essai in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.load(r)
        except Exception:
            time.sleep(0.8)
    return None

d = json.load(open(sys.argv[1]))
verite = [r for r in d["series"] if r["wikidata"] and r["wikidata"]["tvmaze"]]
print(f"vérité terrain : {len(verite)} paires TMDB↔TVmaze (P4983 + P8600)")

stats = {
    "total": 0, "sans_resultat": 0,
    "top1_bon": 0, "top1_bon_seuil": 0,        # top1 correct / correct ET score>=0.9
    "top1_mauvais_seuil": 0,                    # FAUX POSITIF du seuil seul
    "bon_dans_liste": 0,
    "imdb_dispo_top1": 0,                       # externals.imdb présent sur le top1
    "imdb_confirme_bon": 0,                     # égalité imdb confirme le bon top1
    "imdb_veto_mauvais": 0,                     # égalité imdb aurait rejeté le mauvais top1
    "imdb_rescue": 0,                           # bon trouvé plus loin dans la liste via imdb
}
faux_positifs = []

for r in verite:
    bon_id = int(r["wikidata"]["tvmaze"])
    imdb_wd = r["wikidata"]["imdb"] or None
    q = urllib.parse.quote(r["nom"] or "")
    res = get(f"https://api.tvmaze.com/search/shows?q={q}") or []
    time.sleep(0.45)
    stats["total"] += 1
    if not res:
        stats["sans_resultat"] += 1
        continue
    ids = [hit["show"]["id"] for hit in res]
    top = res[0]
    top_imdb = (top["show"].get("externals") or {}).get("imdb")
    if bon_id in ids:
        stats["bon_dans_liste"] += 1
    if ids[0] == bon_id:
        stats["top1_bon"] += 1
        if top["score"] >= 0.9:
            stats["top1_bon_seuil"] += 1
        if top_imdb and imdb_wd:
            stats["imdb_dispo_top1"] += 1
            if top_imdb == imdb_wd:
                stats["imdb_confirme_bon"] += 1
    else:
        if top["score"] >= 0.9:
            stats["top1_mauvais_seuil"] += 1
            faux_positifs.append((r["nom"], r["strate"], top["show"]["name"], round(top["score"], 3)))
        if top_imdb and imdb_wd:
            stats["imdb_dispo_top1"] += 1
            if top_imdb != imdb_wd:
                stats["imdb_veto_mauvais"] += 1
        # le bon est-il récupérable plus loin, par égalité imdb ?
        for hit in res[1:]:
            h_imdb = (hit["show"].get("externals") or {}).get("imdb")
            if imdb_wd and h_imdb == imdb_wd and hit["show"]["id"] == bon_id:
                stats["imdb_rescue"] += 1
                break

for k, v in stats.items():
    print(f"  {k:<22} {v}")
print("\nfaux positifs du seuil 0.9 seul :")
for nom, strate, choisi, score in faux_positifs:
    print(f"  [{strate}] {nom!r} -> {choisi!r} (score {score})")
