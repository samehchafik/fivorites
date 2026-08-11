-- Le canal vidéo : bandes-annonces et extraits, extraits du brut collecté.
--
-- TMDB renvoie déjà les vidéos — `videos` est dans `SERIES_APPEND` depuis le
-- premier jour, et dans `SEASON_APPEND` pour les saisons. La donnée dort donc
-- dans `raw_source.payload` depuis le début, sans que rien ne la lise.
--
-- Pourquoi une table plutôt qu'une lecture du payload à la volée : le payload
-- d'une série pèse plusieurs centaines de kilo-octets, et l'ouvrir pour en
-- tirer trois clés YouTube coûte plus cher que tout le reste de la fiche. Une
-- projection normalisée rend la question « quelle est la bande-annonce de
-- cette série » indexable, et la rend surtout posable sur le catalogue entier
-- — « combien de séries ont une bande-annonce en français » est une requête,
-- plus un parcours de 300 000 documents.
--
-- Pourquoi une colonne `source` alors qu'il n'y a que TMDB aujourd'hui : les
-- vidéos sont le seul média que TMDB ne sert pas lui-même — il donne une clé
-- chez un hébergeur tiers. Le jour où l'on complètera par un autre fournisseur
-- (les bandes-annonces françaises manquent souvent), il n'y aura pas de
-- migration à faire, seulement des lignes d'une autre provenance. La clé
-- primaire porte l'hébergeur et la clé, pas la source : deux fournisseurs qui
-- désignent la même vidéo YouTube ne créent pas de doublon.

create table sourcing.video (
    id_tmdb integer not null references sourcing.tmdb_catalog (id) on delete cascade,
    site    text    not null,                    -- YouTube | Vimeo
    cle     text    not null,                    -- l'identifiant chez l'hébergeur

    source     text    not null default 'tmdb',  -- qui nous l'a fait connaître
    type       text    not null,                 -- Trailer | Teaser | Clip | Featurette | ...
    nom        text,
    lang       text    not null default '',      -- iso_639_1 ; '' si non précisée
    officiel   boolean not null default false,
    publie_le  timestamptz,
    definition integer,                          -- 1080, 720 — tel que déclaré
    -- Numéro de saison quand la vidéo vient d'une fiche de saison, null quand
    -- elle vient de la série. Une même bande-annonce listée aux deux endroits
    -- ne fait qu'une ligne : c'est la première vue qui garde son rattachement.
    saison     integer,

    raw_source_id bigint references sourcing.raw_source (id) on delete set null,
    fetched_at    timestamptz not null default now(),

    -- L'ordre de préférence, calculé une fois plutôt que réécrit dans chaque
    -- requête : une bande-annonce officielle passe devant une officieuse, et
    -- une bande-annonce devant un teaser, un teaser devant un extrait. La
    -- langue n'entre pas ici — elle dépend de qui regarde, pas de la vidéo.
    priorite integer generated always as (
        case type
            when 'Trailer'    then 0
            when 'Teaser'     then 1
            when 'Clip'       then 2
            when 'Featurette' then 3
            else 4
        end * 2 + case when officiel then 0 else 1 end
    ) stored,

    primary key (id_tmdb, site, cle)
);

comment on table sourcing.video is
    'Projection des vidéos du brut TMDB. Une ligne par vidéo, dédoublonnée sur (hébergeur, clé).';
comment on column sourcing.video.priorite is
    'Ordre de préférence : bande-annonce officielle d''abord. Plus petit = meilleur.';

-- La requête de la fiche : « les vidéos de cette série, la meilleure d'abord ».
create index video_serie_idx on sourcing.video (id_tmdb, priorite, publie_le desc nulls last);


-- L'état de la passe, pour qu'elle reprenne là où elle s'est arrêtée.
--
-- Sans lui, impossible de distinguer « série jamais examinée » de « série
-- examinée, sans aucune vidéo » — or le second cas est fréquent et il ne faut
-- pas le rouvrir à chaque passe. `raw_source_id` dit quelle version du brut a
-- été lue : une re-collecte rend l'examen caduc, et cela se voit.
create table sourcing.video_scan (
    id_tmdb       integer primary key references sourcing.tmdb_catalog (id) on delete cascade,
    raw_source_id bigint references sourcing.raw_source (id) on delete set null,
    videos        integer     not null default 0,
    scanned_at    timestamptz not null default now()
);

comment on table sourcing.video_scan is
    'Ce que la passe vidéo a déjà examiné — y compris les séries sans aucune vidéo.';
