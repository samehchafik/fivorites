-- Schéma `sourcing` : la couche de collecte.
--
-- Une seule base pour tout le projet (`fivorites_v2`), un schéma par domaine.
-- Ici la collecte ; les couches métier (faits, axes) auront les leurs. Ça évite
-- l'éparpillement en bases séparées tout en gardant des frontières nettes — et
-- ça permet de joindre entre domaines sans dblink ni FDW.
--
-- Ces deux tables portent la correction des trois faiblesses du pipeline V1 :
-- le brut jeté dans des fichiers jamais relus, l'état incrémental stocké dans
-- trois JSON sur disque, et l'absence de fraîcheur par item.

create schema if not exists sourcing;


create table sourcing.raw_source (
    id             bigserial   primary key,
    source         text        not null,   -- tmdb | wikidata | wikipedia
    kind           text        not null,   -- tv | tv_season | entity | extract
    source_id      text        not null,   -- '1399' | '1399/s2' | 'Q23572'
    lang           text,                   -- null quand la source est monolingue
    fetched_at     timestamptz not null default now(),
    http_status    integer     not null,
    payload        jsonb,                  -- null si la requête a échoué
    payload_sha256 bytea       not null
);

comment on table sourcing.raw_source is
    'Append-only. Jamais d''UPDATE, jamais d''interprétation. Toute la dérivation relit ceci.';
comment on column sourcing.raw_source.http_status is
    'Un 404 est un résultat, pas une erreur : TMDB supprime des séries et on veut le savoir.';

-- Un contenu strictement identique n'est stocké qu'une fois. coalesce() parce
-- qu'un index unique considère chaque NULL comme distinct.
create unique index raw_source_dedup_idx
    on sourcing.raw_source (source, kind, source_id, coalesce(lang, ''), payload_sha256);

-- La requête que fait la dérivation : « la dernière version de cet objet ».
create index raw_source_latest_idx
    on sourcing.raw_source (source, kind, source_id, fetched_at desc);

create index raw_source_payload_idx
    on sourcing.raw_source using gin (payload jsonb_path_ops);


create table sourcing.fetch_state (
    source          text        not null,
    kind            text        not null,
    source_id       text        not null,
    priority        smallint    not null default 3,  -- 1 haute, 2 moyenne, 3 fond de catalogue
    last_fetched_at timestamptz,
    last_success_at timestamptz,
    last_changed_at timestamptz,
    attempts        integer     not null default 0,
    last_status     integer,
    last_error      text,
    primary key (source, kind, source_id)
);

comment on table sourcing.fetch_state is
    'Remplace series_done_by_ids.json, tv_recently.changed_by_ids.json et series-data.json de la V1.';
comment on column sourcing.fetch_state.last_fetched_at is
    'Quand on a regardé — distinct de last_changed_at, quand ça a bougé.';

-- L'ordonnancement du rafraîchissement : les plus prioritaires et les plus
-- anciens d'abord, jamais-vus en tête.
create index fetch_state_due_idx
    on sourcing.fetch_state (priority, last_fetched_at nulls first);
