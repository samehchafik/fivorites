-- L'actualité des œuvres : la collecte RSS, sa dérivation, et le curseur des
-- diffs internes. L'architecture complète est dans
-- doc/architecture-actualite.md ; ici, le pourquoi de chaque table.
--
-- Le principe reconduit est celui de tout le sourcing : un brut append-only
-- jamais interprété, une dérivation rejouable à volonté. Deux invariants du
-- dépôt sont préservés tels quels — `raw_source` reste exclusivement TMDB (le
-- RSS a sa table brute à lui), et rien ne se collecte et ne s'interprète dans
-- le même geste.

-- ---------------------------------------------------------------------------
-- Le registre des flux. En base et pas dans le code : ajouter un flux est une
-- ligne SQL ou un geste admin, pas un déploiement. Un flux désactivé reste en
-- base — l'historique de ses items ne disparaît pas avec lui.
--
-- L'état de collecte (etag, last_modified…) vit ICI et pas dans `fetch_state` :
-- ces colonnes n'existent que pour le GET conditionnel HTTP, et les ajouter à
-- une table partagée par toutes les sources pour un seul usage la brouillerait.
create table sourcing.rss_feed (
    id              bigint generated always as identity primary key,
    url             text not null unique,
    editeur         text not null,           -- 'telerama' | 'allocine' | …
    -- Indice de liaison, pas une contrainte : « ce flux parle de livres »
    -- aide le matching à choisir entre homonymes d'univers différents.
    univers         text[],
    actif           boolean not null default true,
    etag            text,
    last_modified   text,
    last_status     integer,
    last_success_at timestamptz,
    last_error      text
);

comment on table sourcing.rss_feed is
    'Le registre des flux RSS suivis. L''état du GET conditionnel vit ici — un flux, un état.';

-- ---------------------------------------------------------------------------
-- Le brut RSS, append-only, pendant de `raw_source`.
--
-- Le payload est normalisé en LISTE BLANCHE à l'entrée : title, link, guid,
-- published, tags, et summary tronqué à 500 caractères à la phrase. Tout le
-- reste est jeté — `content:encoded` en tête, car certains éditeurs y
-- expédient l'article entier et la frontière juridique du projet est de ne
-- jamais le stocker. Écarter à l'entrée plutôt qu'à l'affichage : ce qui
-- n'est pas en base ne peut pas fuir.
create table sourcing.raw_rss_item (
    id         bigint generated always as identity primary key,
    feed_id    bigint not null references sourcing.rss_feed (id),
    guid       text not null,               -- <guid> du flux, le lien à défaut
    fetched_at timestamptz not null default now(),
    digest     bytea not null,              -- empreinte du payload normalisé
    payload    jsonb not null,
    -- Un item ré-émis à l'identique n'écrit rien ; un item corrigé par
    -- l'éditeur écrit une nouvelle ligne. Même règle que raw_source.
    unique (feed_id, guid, digest)
);

create index raw_rss_item_recent_idx
    on sourcing.raw_rss_item (feed_id, fetched_at desc);

comment on table sourcing.raw_rss_item is
    'Append-only, jamais interprété. Payload en liste blanche : jamais le contenu d''article.';

-- ---------------------------------------------------------------------------
-- La dérivation : l'événement daté, typé, rattaché (ou non) à une œuvre.
--
-- Le CHECK est la fermeture du vocabulaire, et il n'est pas décoratif : c'est
-- un LLM qui écrira cette colonne pour le RSS, et une valeur inventée doit
-- être une erreur bruyante au moment où elle se produit — pas une catégorie
-- fantôme que les requêtes des consommateurs rateront en silence.
create table sourcing.actualite (
    id              bigint generated always as identity primary key,
    oeuvre_id       bigint references sourcing.oeuvre (id),  -- null = non liée
    type_evenement  text not null check (type_evenement in (
        'saison_annoncee', 'date_diffusion', 'diffusion_terminee', 'annulation',
        'sortie', 'parution', 'critique', 'adaptation', 'prix', 'deces', 'autre'
    )),
    survenu_le      date not null,
    titre           text not null,
    url             text,                    -- null pour les diffs internes
    editeur         text not null,           -- 'tmdb' | 'telerama' | …
    raw_source_id   bigint references sourcing.raw_source (id),
    raw_rss_item_id bigint references sourcing.raw_rss_item (id),
    -- null = liaison certaine (diff interne, c'est notre propre pivot).
    confiance_liaison real,
    derive_at       timestamptz not null default now(),
    -- Une provenance, exactement une : un événement vient d'un diff de fiche
    -- OU d'un item RSS, jamais des deux, jamais d'aucun.
    check ((raw_source_id is null) <> (raw_rss_item_id is null))
);

-- Les clés naturelles du rejeu, partielles parce que la provenance l'est.
-- `oeuvre_id` reste DEHORS : une liaison corrigée doit mettre à jour la
-- ligne, pas la doubler.
create unique index actualite_diff_idx
    on sourcing.actualite (raw_source_id, type_evenement)
    where raw_source_id is not null;
create unique index actualite_rss_idx
    on sourcing.actualite (raw_rss_item_id, type_evenement)
    where raw_rss_item_id is not null;

-- La requête des consommateurs : « l'actualité de cette œuvre, récente
-- d'abord ». Partiel — une actualité non liée ne sert pas la fiche.
create index actualite_oeuvre_idx
    on sourcing.actualite (oeuvre_id, survenu_le desc)
    where oeuvre_id is not null;

comment on table sourcing.actualite is
    'La dérivation : événements datés, typés, sourcés. Se vide et se reconstruit par fenêtre — le brut fait foi.';

-- ---------------------------------------------------------------------------
-- Le cache de l'étape payée. La dérivation est rejouable, mais son typage
-- passe par un appel LLM : sans ce cache, chaque rejeu repaierait un travail
-- identique, et le mode d'itération annoncé (corriger, rejouer) se
-- découragerait de lui-même. La règle qu'il matérialise : on paie quand ce
-- qu'on a changé est ce qui coûte. Changer le code de liaison ne repaie
-- rien ; changer le prompt repaie, et c'est légitime.
create table sourcing.actualite_typage (
    digest         bytea not null,           -- l'item, par son empreinte
    prompt_sha256  text  not null,           -- la consigne, par la sienne
    type_evenement text  not null,
    survenu_le     date,                     -- extraite par le modèle, si sûre
    cree_at        timestamptz not null default now(),
    primary key (digest, prompt_sha256)
);

comment on table sourcing.actualite_typage is
    'Cache du typage LLM : (item, prompt) -> verdict. Rejouer la dérivation ne repaie que si le prompt a changé.';

-- ---------------------------------------------------------------------------
-- Le point de reprise des diffs internes. `raw_source` est append-only à ids
-- croissants : un high-water mark par kind suffit, et il est honnête — la
-- reprise est une comparaison d'entiers, jamais un scan.
create table sourcing.actualite_curseur (
    kind            text primary key,        -- 'tv' | 'movie'
    dernier_raw_id  bigint not null default 0,
    avance_at       timestamptz not null default now()
);

comment on table sourcing.actualite_curseur is
    'Le dernier raw_source.id dont les diffs ont été dérivés, par kind. Le remettre à 0 rejoue tout.';
