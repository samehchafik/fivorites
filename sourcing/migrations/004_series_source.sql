-- L'enrichissement externe : ce qu'une source tierce apporte sur une série.
--
-- Une ligne par (série, source, langue) — et non une ligne par téléchargement.
-- C'est la différence avec `raw_source`, qui garde la réponse HTTP brute et n'en
-- sait rien d'autre. Ici on répond à une question que le brut ne sait pas poser :
-- « pour cette série, qu'a-t-on trouvé ailleurs, et combien ça pèse ? »
--
-- Cette table est donc de la **dérivation** : elle se reconstruit entièrement
-- depuis `raw_source`, sans réseau. Le payload continue d'aller dans
-- `raw_source`, la fraîcheur dans `fetch_state` (source = 'wikipedia', etc. —
-- ces deux tables sont déjà génériques, rien à y ajouter).
--
-- Elle sert deux choses :
--   le rapport de couverture du lot 5 — matière disponible par série et par
--     source, sans jamais relire un seul article ;
--   le constructeur de dossier de notation — `series_id → texte prêt à noter`
--     devient un `select` sur une clé primaire.

create table sourcing.series_source (
    id_tmdb   integer not null references sourcing.tmdb_catalog (id) on delete cascade,

    source    text    not null,          -- wikidata | wikipedia | tvmaze | elcinema
    lang      text    not null default '',  -- édition linguistique ; '' si la source est monolingue
    source_id text    not null,          -- 'Q23572' | 'باب الحارة' | '82'
    url       text,                      -- la page qui fait autorité, pour vérifier à la main

    content   text,                      -- le texte, tel qu'extrait — null si la source n'en donne pas
    media     jsonb   not null default '[]'::jsonb,  -- [{"type": "poster", "url": "…"}, …]

    -- Comment le raccordement s'est fait. Sans cette colonne, le taux de
    -- résolution par chemin redevient une étude à refaire ; avec elle, c'est un
    -- `group by`. La mesure du 2026-08-06 disait que l'entrée par identifiant
    -- TMDB (P4983) ne rapporte que six séries de langue arabe là où l'entrée par
    -- IMDb (P345) échoue — un chiffre qu'on veut pouvoir revérifier sans rejouer
    -- la collecte.
    resolved_by text,                    -- p4983 | p345 | sitelink | title

    fetched_at  timestamptz not null default now(),

    primary key (id_tmdb, source, lang),

    -- `media` doit être un tableau. La contrainte le dit par son nom ; sans
    -- elle, l'erreur remontée serait « cannot get array length of a non-array »,
    -- levée par la colonne calculée, qui ne désigne ni la table ni la colonne.
    constraint series_source_media_is_array check (jsonb_typeof(media) = 'array')
);

-- Deux compteurs calculés plutôt que deux agrégats à écrire à chaque fois.
-- Le rapport de couverture trie et seuille sur eux (l'étude arabophone retenait
-- « ≥ 2 000 caractères cumulés ») : les stocker évite de décompresser le texte
-- de 228 000 séries pour obtenir un nombre.
-- Le `case` n'est pas une précaution en double de la contrainte : une colonne
-- calculée est évaluée *avant* elle. Sans ce garde-fou, `jsonb_array_length`
-- lèverait la première, et le message que verrait l'appelant ne dirait ni la
-- table, ni la colonne, ni ce qu'on attendait.
alter table sourcing.series_source
    add column content_chars integer generated always as (coalesce(length(content), 0)) stored,
    add column media_count   integer generated always as (
        case when jsonb_typeof(media) = 'array' then jsonb_array_length(media) else 0 end
    ) stored;

comment on table sourcing.series_source is
    'Dérivée de raw_source, reconstructible sans réseau. Une ligne par série, source et langue.';
comment on column sourcing.series_source.content is
    'Le texte destiné à la notation. La source de vérité reste le payload dans raw_source.';
comment on column sourcing.series_source.resolved_by is
    'Le chemin qui a raccordé la série. Rend le taux de résolution mesurable par requête.';
comment on column sourcing.series_source.lang is
    'Chaîne vide plutôt que NULL : la langue fait partie de la clé, et un NULL y serait interdit.';

-- « Que reste-t-il à enrichir pour cette source ? » — une anti-jointure sur
-- tmdb_catalog, filtrée par source. La clé primaire commence par `id_tmdb`,
-- elle ne sait pas répondre.
create index series_source_pending_idx
    on sourcing.series_source (source, id_tmdb);

-- « Où y a-t-il assez de matière pour noter ? » — index partiel : les lignes
-- sans texte (une entrée Wikidata, une galerie) sont la majorité et n'ont rien
-- à faire dans cet index.
create index series_source_matter_idx
    on sourcing.series_source (source, lang, content_chars desc)
    where content_chars > 0;
