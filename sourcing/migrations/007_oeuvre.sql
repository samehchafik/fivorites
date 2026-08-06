-- L'identifiant d'œuvre — le pivot que les sources externes n'offrent pas.
--
-- Le constat (mesuré le 2026-08-06) : la moitié des items « série » de Wikidata
-- n'a pas d'identifiant TMDB, 300 des 480 séries de langue arabe n'ont AUCUN
-- identifiant externe, et TVmaze ne porte jamais d'id TMDB — ses seuls ponts
-- sont l'imdb_id et Wikidata (P8600). Aucun identifiant universel n'existe
-- dehors : on crée le nôtre.
--
-- `oeuvre` est ce pivot. Chaque identifiant externe y est NULLABLE et UNIQUE :
-- une œuvre peut n'être connue que de Wikidata, que de TVmaze, ou de personne
-- (saisie par titre). C'est ce qui permet d'accueillir les séries hors TMDB —
-- khaleeji notamment — sans changer d'architecture.
--
-- C'est aussi, par anticipation, l'`oeuvre_id` que la couche 2 (notation)
-- attend, et le pendant du `catalog.series(id, id_tmdb, …)` du lot 4 : le jour
-- où la couche 1 existe, elle dérive d'ici.
--
-- La réconciliation tardive est prévue par construction : une série saisie via
-- son QID puis apparaissant un jour dans TMDB, c'est la MÊME ligne d'oeuvre qui
-- gagne un id_tmdb — les index uniques empêchent le doublon de naître.

create table sourcing.oeuvre (
    id           bigserial primary key,
    univers      text not null default 'series',   -- series | movies | books | bd | musics

    -- Les identifiants externes, tous facultatifs. Ce qu'on sait, quand on le sait.
    id_tmdb      integer references sourcing.tmdb_catalog (id),
    wikidata_qid text,
    imdb_id      text,
    tvmaze_id    integer,

    -- Pour les œuvres hors TMDB, c'est tout ce qu'on a ; pour les autres, c'est
    -- du confort de lecture. La vérité TMDB reste dans tmdb_catalog/raw_source.
    titre        text,
    annee        integer,

    created_at   timestamptz not null default now()
);

comment on table sourcing.oeuvre is
    'Le pivot d''identité des œuvres. Tous les identifiants externes sont nullables : '
    'une œuvre peut exister sans TMDB (khaleeji), sans Wikidata, ou sans rien (titre seul).';

-- Uniques et partiels : NULL ne compte pas, et deux œuvres ne peuvent pas
-- revendiquer le même identifiant externe dans un même univers.
create unique index oeuvre_tmdb_idx on sourcing.oeuvre (univers, id_tmdb)
    where id_tmdb is not null;
create unique index oeuvre_qid_idx on sourcing.oeuvre (univers, wikidata_qid)
    where wikidata_qid is not null;
create unique index oeuvre_tvmaze_idx on sourcing.oeuvre (univers, tvmaze_id)
    where tvmaze_id is not null;
create index oeuvre_imdb_idx on sourcing.oeuvre (imdb_id) where imdb_id is not null;

-- ---------------------------------------------------------------------------
-- riche_source se raccroche au pivot. `id_tmdb` et `raw_source_id` deviennent
-- nullables : une œuvre hors TMDB n'a ni l'un ni l'autre, et c'est prévu.

-- Les œuvres des enrichissements existants, d'abord.
insert into sourcing.oeuvre (univers, id_tmdb)
select distinct 'series', id_tmdb from sourcing.riche_source;

alter table sourcing.riche_source
    add column id bigserial,
    add column oeuvre_id bigint;

update sourcing.riche_source rs
set oeuvre_id = o.id
from sourcing.oeuvre o
where o.univers = 'series' and o.id_tmdb = rs.id_tmdb;

alter table sourcing.riche_source
    drop constraint riche_source_pkey,
    alter column oeuvre_id set not null,
    alter column id_tmdb drop not null,
    alter column raw_source_id drop not null,
    add primary key (id),
    add constraint riche_source_oeuvre_fkey
        foreign key (oeuvre_id) references sourcing.oeuvre (id) on delete cascade;

-- L'unicité qui portait sur (id_tmdb, source, lang) porte désormais sur le
-- pivot : c'est lui qui rassemble les lignes d'une même œuvre, TMDB ou pas.
create unique index riche_source_oeuvre_source_idx
    on sourcing.riche_source (oeuvre_id, source, lang);

comment on column sourcing.riche_source.oeuvre_id is
    'Le pivot. C''est lui qui attache entre elles les lignes d''une même œuvre, '
    'y compris quand elle n''existe pas dans TMDB (id_tmdb et raw_source_id null).';
comment on column sourcing.riche_source.id_tmdb is
    'Null pour une œuvre hors TMDB. Sinon, redondant avec oeuvre.id_tmdb, gardé pour les jointures directes.';
comment on column sourcing.riche_source.raw_source_id is
    'La fiche TMDB au moment de l''enrichissement. Null pour une œuvre hors TMDB.';
