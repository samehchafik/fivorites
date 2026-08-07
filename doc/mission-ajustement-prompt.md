# Mission : stabiliser le prompt de notation (phase 1)

Note autonome. Elle contient tout ce qu'il faut pour travailler le prompt de
notation dans un fil neuf, sans autre contexte. Lire en complément :
`doc/v2-notation-axes.md` (la définition des axes, référence de fond) et
`doc/contrat-donnees-admin.md` (où vit la donnée).

## 1. Le but, en trois phrases

Fivorites note chaque série sur **6 axes de goût** (1 à 10) pour construire un
« vecteur de goût » par œuvre. La notation de masse sera faite par un LLM
(OpenAI), puis distillée dans une régression interne — mais tout repose sur un
**prompt de notation stable** : tant que deux modèles raisonnables lisent le
même dossier et rendent des notes qui divergent, c'est le prompt qui est
ambigu, pas les modèles. La mission est d'itérer sur ce prompt jusqu'à ce que
les verdicts convergent au niveau du bruit.

## 2. Les deux juges — et pourquoi deux familles

| Rôle | Qui | Comment |
|---|---|---|
| **Noteur** | OpenAI `gpt-5.4-mini` | par l'API, sortie contrainte au schéma JSON |
| **Contre-juge** | Claude, via **claude.ai (site web, à la main)** | copier-coller — il n'y a **pas** de clé Anthropic et il n'en faut pas |

Le contre-juge est d'une autre famille de modèles, exprès : toute la chaîne
(notes de masse, embeddings, poids) descend d'OpenAI, et seul un juge d'une
autre lignée peut révéler un biais que cette lignée partagerait. Règles
absolues :

- **Les notes Claude n'entraînent jamais les poids.** Elles sont stockées sous
  le modèle `claude-web-manuel` et l'entraînement les exclut (`modele not like
  'claude%'`). Claude contredit, ou pas — c'est tout son rôle.
- **Ne pas chercher à automatiser le contre-jugement** avec une clé Anthropic :
  l'utilisateur n'en a pas et n'en veut pas. Le circuit manuel via claude.ai
  est le circuit nominal.

## 3. Ce que les juges lisent : le dossier

Le dossier est un texte **anglais uniquement**, construit de façon
**déterministe** depuis la base (`admin/src/fiv_admin/dossier.py`) — mêmes
données, même texte, même empreinte sha256. Sections, dans l'ordre : TITLE,
FACTS, GENRES, KEYWORDS, OVERVIEW, SEASON OVERVIEWS, EPISODE SYNOPSES
(10 épisodes échantillonnés sur tout l'arc), MEDIA (légendes des visuels si
elles ont été générées), WIKIPEDIA (en, tronqué à 6 000 caractères). Cible :
~2 000 tokens.

L'empreinte du dossier ET celle du prompt accompagnent chaque note : rien
n'est comparable sans ces deux sha256. C'est pour ça qu'on ne modifie jamais
un barème existant — on en **fige une nouvelle version** (§6).

## 4. L'interface — où tout se passe

Admin en production : `http://ifrit.fr:8182` (en local : `make -C admin dev`,
ou `make -C admin serve` sur le build). Ouvrir une série depuis le catalogue,
puis l'onglet **Training 1** — ou directement par l'URL :

```
http://ifrit.fr:8182/?id=1399&onglet=training1
```

Dans l'onglet :

1. **Le dossier** se lit à gauche — c'est exactement ce que les juges reçoivent.
2. **Barème** : sélecteur de version + la consigne (system prompt), éditable
   librement. Chaque essai est tracé par empreinte, sauvé ou non.
3. **« Noter (OpenAI) »** : envoie consigne + dossier au noteur. Les notes
   s'affichent et s'enregistrent.
4. **« Copier pour Claude.ai »** : met dans le presse-papier la consigne + une
   instruction de format de réponse (`axis: score`, une ligne par axe) + le
   dossier. À coller dans une conversation claude.ai.
5. **Bloc « Contre-note claude.ai »** (toujours visible) : coller la réponse
   de claude.ai telle quelle — les lignes `luminosite: 7` remplissent les
   cases toutes seules. Ajuster au besoin, « Enregistrer la contre-note ».
6. **Les écarts** s'affichent par axe, colorés : teal ≤ 1, jaune ≤ 2, rouge
   au-delà.
7. **« Légender les visuels »** (en-tête) : décrit backdrops et stills
   d'épisodes via gpt vision et les fige — ajoute la section MEDIA au dossier.
   Payé une fois par image, jamais recommencé.
8. **« Figer comme version »** : quand une formulation tient, l'enregistrer
   sous un nouveau nom de version (ex. `v2-luminosite-precisee`).

La page se recharge sans rien perdre : le dernier essai se relit du journal.

## 5. Le protocole d'itération

Boucle, série par série :

```
choisir une série → (option) légender les visuels → Noter (OpenAI)
→ Copier pour Claude.ai → coller dans claude.ai → recopier la réponse
→ Enregistrer la contre-note → lire les écarts par axe
```

Lecture des écarts (le bruit de fond mesuré test-retest est d'environ
**1 point**) :

- **écart ≤ 1** sur un axe : au niveau du bruit — le prompt tient sur cet axe.
- **1 < écart ≤ 2** : zone grise — noter l'axe et la série, surveiller s'il
  récidive sur d'autres œuvres.
- **écart > 2** : le prompt est **ambigu sur cet axe**. C'est là qu'on
  travaille.

Comment corriger un axe qui diverge :

- **Resserrer la définition** de l'axe dans la consigne : une phrase qui dit
  ce que l'axe mesure ET ce qu'il ne mesure pas (« humour : la densité de
  comique volontaire — pas le ton léger, pas l'absurde involontaire »).
- **Renforcer les ancres** : chaque axe a des œuvres-repères aux deux bouts de
  l'échelle (le barème v1 en contient, ex. Requiem for a Dream = 1 en
  luminosité, Paddington = 10). Si deux juges placent la même série de part et
  d'autre du milieu, l'ancre du milieu manque : en ajouter une (score 5-6).
- **Autoriser le « ne sait pas »** : la consigne permet un score null quand la
  matière manque — vérifier que les deux juges l'utilisent au lieu de deviner.
- **Ne pas sur-adapter** à une série : une correction doit se vérifier sur les
  séries déjà notées (les rejouer coûte un clic) et sur des œuvres variées.

Échantillon de travail : viser la **diversité avant le volume** — une série
sombre et une lumineuse, une comédie, un drame exigeant, une série grand
public, et impérativement des œuvres **arabes et turques** (le catalogue les
sert à égalité ; un prompt qui ne converge que sur les séries US est un prompt
raté). Une quinzaine de séries bien choisies suffisent à stabiliser.

**Critère de fin de mission** : sur les ~15 dernières notations, écart moyen
OpenAI/Claude ≤ 1 point, aucun axe systématiquement > 2. Alors figer la
version finale du barème — c'est elle qui nourrira la notation de masse et la
phase 2 (poids).

## 6. Versionner, jamais écraser

Un barème (`notation.rubric`) est immuable : changer une ancre change toutes
les notes qui en découlent, la version EST la provenance. Le flux : éditer la
consigne dans la page (l'essai est tracé par empreinte même non sauvé) →
quand ça tient, « Figer comme version » avec un nom parlant. L'API refuse
d'écraser une version existante (409).

## 7. Où vit la donnée (pour analyser, pas pour écrire)

Base Postgres `fivorites_v2`, schéma `notation`. Les tables se remplissent par
l'interface — **ne pas écrire dedans à la main**.

| Table | Contenu |
|---|---|
| `rubric` | les versions de barème : prompt, axes, note |
| `score` | append-only : une ligne par (œuvre, axe, juge), avec `input_sha256` (dossier) et `prompt_sha256` |
| `training_run` | **le journal des essais** : une ligne par notation — prompt en clair, `raw_source_id` de la fiche, JSON `openai` et `claude` côte à côte, horodatages |
| `training_weights` | le journal des poids (phase 2) : une ligne par prompt |
| `media_caption` | les légendes de visuels, figées |

Requêtes utiles pour piloter la mission :

```sql
-- Les essais récents et leurs écarts moyens (openai vs claude)
select tr.id, tr.id_tmdb, tr.created_at, tr.claude_at is not null as contre_note,
       (select round(avg(abs((o.value->>'score')::numeric - (c.value->>'score')::numeric)), 2)
        from jsonb_each(tr.openai->'scores') o
        join jsonb_each(tr.claude->'scores') c using (key)
        where o.value->>'score' is not null and c.value->>'score' is not null) as ecart_moyen
from notation.training_run tr
order by tr.created_at desc limit 20;

-- L'axe qui diverge le plus, tous essais confondus
select o.key as axe,
       round(avg(abs((o.value->>'score')::numeric - (c.value->>'score')::numeric)), 2) as ecart,
       count(*) as essais
from notation.training_run tr,
     jsonb_each(tr.openai->'scores') o,
     jsonb_each(tr.claude->'scores') c
where o.key = c.key
  and o.value->>'score' is not null and c.value->>'score' is not null
group by o.key order by ecart desc;
```

## 8. Le code, si la mission demande d'y toucher

- Dossier : `admin/src/fiv_admin/dossier.py` (sections, échantillonnage)
- Juges : `admin/src/fiv_admin/llm.py` (appels API, schémas de sortie, consigne des légendes)
- Routes : `admin/src/fiv_admin/routes/training.py` (`/api/training/*`)
- Front : `front/src/components/TrainingTab.tsx` (l'atelier), à rebuilder par
  `make -C admin web-build` après modification
- Tests : `make -C admin test` (les juges y sont simulés) ; lint : `make -C admin lint`

Contraintes d'environnement (voir la mémoire du projet et `CLAUDE.md`) :
Python vendorisé dans `admin/vendor` — toujours passer par les cibles du
Makefile, jamais par le Python système ni `uv run` directement. Pas de Docker
en local. Committer et pousser directement sur `main`. Sur le serveur :
`git pull`, `sudo docker compose run --rm admin db migrate` s'il y a une
migration, `sudo docker compose up -d --force-recreate admin` si le code
Python a changé (le front monté en volume ne demande qu'un rechargement).

`OPENAI_API_KEY` doit être dans le `.env` (local : `admin/.env` ; serveur :
`.env` racine à côté du compose). Sans elle, les routes de notation répondent
409 avec un message clair. `ANTHROPIC_API_KEY` reste vide — voulu.
