-- `series_source` devient `riche_source`, et `raw_source` redevient
-- exclusivement TMDB.
--
-- Décision du 2026-08-06 : les réponses des sources tierces (Wikidata,
-- Wikipédia, TVmaze) sont de l'enrichissement, pas de la collecte — elles n'ont
-- rien à faire dans `raw_source`. L'enrichissement se raccroche au brut
-- collecté : `riche_source.raw_source_id` référence la fiche TMDB de la série.
--
-- Ce que ce choix implique, et qui est assumé :
--   * une série doit être **collectée** avant d'être enrichie ;
--   * les faits des sources tierces (pays, langue, lieux P915/P840, dates et
--     diffuseur TVmaze) n'ayant plus de brut où vivre, ils sont conservés dans
--     `riche_source.facts` — sinon ils seraient perdus pour la couche 1 ;
--   * changer un jour la façon d'extraire (texte, faits) imposera de
--     réinterroger les sources, puisque leur réponse n'est plus conservée.
--
-- Table recréée plutôt qu'altérée : c'est le seul moyen de contrôler l'ordre
-- des colonnes — la référence d'abord, `id_tmdb` juste après.

-- 1. Le nettoyage : tout ce que l'enrichissement avait écrit dans le brut.
delete from sourcing.raw_source where source <> 'tmdb';

-- 2. La nouvelle table.
create table sourcing.riche_source (
    raw_source_id bigint  not null references sourcing.raw_source (id) on delete cascade,
    id_tmdb       integer not null references sourcing.tmdb_catalog (id) on delete cascade,

    source    text not null,              -- wikidata | wikipedia | tvmaze
    lang      text not null default '',   -- édition linguistique ; '' si monolingue
    source_id text not null,              -- 'Q23572' | 'صراع العروش' | '82'
    url       text,

    content   text,                       -- le texte destiné à la notation
    media     jsonb not null default '[]'::jsonb,
    facts     jsonb not null default '{}'::jsonb,

    resolved_by text,                     -- p4983 | p345 | p8600 | imdb | title | sitelink
    fetched_at  timestamptz not null default now(),

    -- La clé porte la série, pas la fiche : une re-collecte crée une nouvelle
    -- ligne de brut (append-only), et le ré-enrichissement met simplement
    -- `raw_source_id` à jour au lieu de dupliquer la série.
    primary key (id_tmdb, source, lang),

    constraint riche_source_media_is_array check (jsonb_typeof(media) = 'array')
);

-- Le `case` n'est pas une précaution en double de la contrainte : une colonne
-- calculée est évaluée *avant* elle, et son erreur ne nommerait ni la table ni
-- la colonne.
alter table sourcing.riche_source
    add column content_chars integer generated always as (coalesce(length(content), 0)) stored,
    add column media_count   integer generated always as (
        case when jsonb_typeof(media) = 'array' then jsonb_array_length(media) else 0 end
    ) stored;

comment on table sourcing.riche_source is
    'Enrichissement par les sources tierces, raccroché à la fiche collectée (raw_source_id).';
comment on column sourcing.riche_source.raw_source_id is
    'La fiche TMDB au moment de l''enrichissement. Une re-collecte crée une nouvelle fiche ; '
    'le prochain enrichissement de la série remet cette référence à jour.';
comment on column sourcing.riche_source.facts is
    'Les faits de la source — pays, langue, lieux (P915/P840), dates et diffuseur TVmaze. '
    'Leur seul lieu de vie : les réponses tierces ne sont pas conservées en brut.';
comment on column sourcing.riche_source.resolved_by is
    'Le chemin qui a raccordé la série. Rend le taux de résolution mesurable par requête.';

-- « Où y a-t-il assez de matière pour noter ? » — index partiel : les lignes
-- sans texte sont la majorité et n'ont rien à y faire.
create index riche_source_matter_idx
    on sourcing.riche_source (source, lang, content_chars desc)
    where content_chars > 0;

create index riche_source_pending_idx on sourcing.riche_source (source, id_tmdb);

-- 3. La reprise de l'existant — seules les séries collectées ont une fiche à
--    référencer ; les autres seront reprises une fois la collecte passée.
insert into sourcing.riche_source
       (raw_source_id, id_tmdb, source, lang, source_id, url, content, media,
        resolved_by, fetched_at)
select fiche.id, ss.id_tmdb, ss.source, ss.lang, ss.source_id, ss.url, ss.content,
       ss.media, ss.resolved_by, ss.fetched_at
from sourcing.series_source ss
join (
    select distinct on (source_id) id, source_id::int as id_tmdb
    from sourcing.raw_source
    where source = 'tmdb' and kind = 'tv' and http_status between 200 and 299
    order by source_id, fetched_at desc
) fiche on fiche.id_tmdb = ss.id_tmdb;

drop table sourcing.series_source;
