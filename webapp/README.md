# fiv-webapp — l'API du site public

Le pendant public de `admin/` : un second service FastAPI (port 8183) qui
sert trois familles de routes sous `/api/public` — la **recherche**
instantanée (Elasticsearch, repli ILIKE), les **signaux** de classement d'une
session anonyme (« j'ai vu et aimé », « je n'aime pas », « je veux voir »,
schéma `visiteur`), et les **suggestions** (le graphe Neo4j : les voisins
d'abord, la distance d'empreinte pour compléter). En production il sert aussi
le build Astro versionné de `../www-site`.

Le raisonnement complet est dans [`doc/site-public.md`](../doc/site-public.md).

## Démarrer

```
make bootstrap      # CPython vendorisé + dépendances
make migrate        # le schéma visiteur
make api            # l'API sur 8183, rechargement à chaud
```

Le site en dev : `make -C ../site dev` (Astro sur 4321, /api relayé vers
8183). Les tests : `make test`. La configuration : `.env` (voir
`.env.example`).

Ce service **lit** ce que l'admin entretient : les projections `admin.*_card`
(`fiv-admin catalog refresh`), les index ES (`fiv-admin search reindex`) et
le graphe (`fiv-admin graphe projeter`). Sa seule écriture est le schéma
`visiteur`.
