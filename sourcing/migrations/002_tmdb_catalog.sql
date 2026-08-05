-- Le catalogue TMDB : la liste de toutes les séries connues.
--
-- Alimenté par l'export quotidien `tv_series_ids_MM_DD_YYYY.json.gz`, un fichier
-- public qui ne consomme aucun appel d'API. C'est notre base de sondage : elle
-- permet de connaître la volumétrie réelle et de tirer un échantillon stratifié
-- par popularité sans rien télécharger d'autre.
--
-- Ce n'est pas du brut au sens de `raw_source` : ce n'est pas la réponse d'un
-- objet, c'est un inventaire. D'où sa propre table, avec une ligne par série et
-- non une ligne par téléchargement.

create table sourcing.tmdb_catalog (
    id            integer     primary key,   -- id TMDB de la série
    original_name text,
    popularity    real        not null default 0,
    adult         boolean     not null default false,

    -- Date de l'export dans lequel l'id a été vu pour la dernière fois. Un id
    -- dont la date décroche des autres a disparu de TMDB — c'est la détection
    -- de suppression que la V1 n'avait pas.
    exported_on   date        not null,

    first_seen_at timestamptz not null default now(),
    last_seen_at  timestamptz not null default now()
);

comment on table sourcing.tmdb_catalog is
    'Inventaire du catalogue TMDB, issu de l''export quotidien. Base de sondage pour l''échantillonnage.';

-- L'échantillonnage stratifié trie par popularité ; le fond de catalogue se
-- lit par la fin.
create index tmdb_catalog_popularity_idx on sourcing.tmdb_catalog (popularity desc);

-- « Qu'est-ce qui n'était pas dans le dernier export ? »
create index tmdb_catalog_exported_idx on sourcing.tmdb_catalog (exported_on);
