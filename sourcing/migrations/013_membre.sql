-- Schéma `membre` : les gens, et leurs liens aux œuvres.
--
-- C'est la moitié de la migration V1 → V2 (doc/migration-v1-v2.md) : la V2
-- décrivait des œuvres, jamais des goûts. Ce schéma reçoit les 69 355 membres
-- de la V1 et leurs tops — la matière première du voisinage
-- five → personne → five → personne que le graphe attend (`:FivMembre`).
--
-- Trois décisions, prises dans le document de migration, que le schéma grave :
--
--   1. `oeuvre_id` partout, jamais `id_tmdb`. Une œuvre citée sans identifiant
--      TMDB doit exister quand même — c'est exactement ce que le pivot permet.
--   2. Un membre sans `identifiant` est un membre valide, pas une anomalie :
--      37 006 invités de la V1 ont un pseudo et des tops, aucun compte. Aucune
--      contrainte ne doit supposer qu'un membre a un email.
--   3. `v1_id` unique partout où la V1 fournit une clé : c'est ce qui rend
--      l'import idempotent (`on conflict (v1_id) do update`), donc rejouable.
--
-- Et deux réalités mesurées à l'export, que le schéma ne doit pas contredire :
--
--   * un « top 5 » n'a pas toujours cinq entrées — 476 en ont plus, jusqu'à
--     118. Donc `rang >= 1`, et pas de plafond.
--   * un membre peut avoir plusieurs fives par univers (life + moment, valide
--     ou non) : pas d'unicité (membre, univers, periode) — `v1_id` suffit.

create schema membre;


-- La personne. `profil` porte ce qui n'a pas besoin d'être requêté (bio,
-- avatar, liens, emails secondaires) ; ce qui gouverne l'affichage ou le tri a
-- sa colonne. Le pseudo n'est PAS unique : 2 034 pseudos sont portés par
-- 8 351 personnes en V1, et renommer les gens à leur insu n'est pas un import.
create table membre.membre (
    id                  bigint      generated always as identity primary key,
    v1_id               bigint      unique,
    pseudo              text,
    profil              jsonb       not null default '{}'::jsonb,
    valide              boolean     not null default true,
    bani                boolean     not null default false,
    privacy_v1          text,                 -- le réglage V1, pour mémoire
    creation            timestamptz,
    derniere_maj        timestamptz,
    derniere_connexion  timestamptz,
    importe_le          timestamptz not null default now()
);

create index membre_pseudo_idx on membre.membre (pseudo);


-- Le compte, séparé de la personne — voir décision 2. `password_hash` reste
-- null tant que l'authentification V2 n'est pas écrite : les condensats
-- SHA-256 de la V1 ne sont pas repris (non salés), ils attendent dans
-- l'export, sous secrets/.
create table membre.identifiant (
    membre_id     bigint  primary key references membre.membre (id) on delete cascade,
    email         text    not null unique,
    email_valide  boolean not null default false,
    password_hash text,
    creation      timestamptz
);


-- La correspondance œuvre V1 → pivot V2. C'est la table qui rend l'import des
-- positions possible ET rejouable : une œuvre créée depuis sa fiche V1 n'a
-- aucune clé naturelle (pas d'id TMDB), seul ce registre sait qu'elle existe
-- déjà. `methode` dit comment la correspondance a été obtenue :
--   tmdb   — l'id TMDB de la V1 a retrouvé le pivot
--   titre  — rapprochement titre normalisé + année (±1, candidat unique)
--   cree   — œuvre créée en V2 depuis la fiche V1
create table membre.oeuvre_v1 (
    univers   text   not null,
    v1_id     bigint not null,
    oeuvre_id bigint not null references sourcing.oeuvre (id) on delete cascade,
    id_tmdb   integer,
    methode   text   not null,
    primary key (univers, v1_id)
);

create index oeuvre_v1_oeuvre_idx on membre.oeuvre_v1 (oeuvre_id);


-- Le top d'un membre dans un univers. `visibilite` gouverne l'affichage V2 —
-- 'public' à l'import, décision du 2026-08-20 — et `privacy_v1` garde
-- l'intention d'origine ('freinds' à 99,8 %), pour le jour où de vrais
-- réglages existeront.
create table membre.five (
    id            bigint  generated always as identity primary key,
    v1_id         bigint  unique,
    membre_id     bigint  not null references membre.membre (id) on delete cascade,
    univers       text    not null,
    periode       text    not null default 'life',   -- life | moment | year
    visibilite    text    not null default 'public',
    privacy_v1    text,
    titre         text,
    valide        boolean not null default true,
    creation      timestamptz,
    derniere_maj  timestamptz
);

create index five_membre_idx on membre.five (membre_id, univers);


-- Une œuvre à un rang d'un top. C'est l'arête du graphe communautaire :
-- (:FivMembre)-[:FIV_CITE {rang}]->(:FivOeuvre) se projettera d'ici.
-- Le « pourquoi » est du texte écrit par le membre — précieux et irremplaçable.
create table membre.five_position (
    five_id     bigint  not null references membre.five (id) on delete cascade,
    rang        integer not null check (rang >= 1),
    oeuvre_id   bigint  not null references sourcing.oeuvre (id) on delete cascade,
    titre_saisi text,
    pourquoi    text,
    commentaire text,
    primary key (five_id, rang)
);

create index five_position_oeuvre_idx on membre.five_position (oeuvre_id);


-- « Ce membre a découvert cette œuvre » — l'origine (le top d'où venait la
-- suggestion) reste en JSON : c'est une trace V1, pas une clé à joindre.
create table membre.decouverte (
    membre_id bigint not null references membre.membre (id) on delete cascade,
    oeuvre_id bigint not null references sourcing.oeuvre (id) on delete cascade,
    origine   jsonb,
    creation  timestamptz,
    valide    boolean not null default true,
    primary key (membre_id, oeuvre_id)
);

create index decouverte_oeuvre_idx on membre.decouverte (oeuvre_id);


-- L'avis rédigé. `reponse_a` reconstruit les fils de discussion de la V1 —
-- rempli en seconde passe à l'import, une fois tous les avis présents.
--
-- La clé V1 porte l'univers : `movies.reviews` et `series.reviews` étaient
-- deux tables aux séquences indépendantes, le même numéro y désigne deux avis
-- différents. Mesuré à l'import : 287 avis, 198 seulement sous un `v1_id` nu.
create table membre.avis (
    id           bigint  generated always as identity primary key,
    v1_univers   text,
    v1_id        bigint,
    unique (v1_univers, v1_id),
    membre_id    bigint  not null references membre.membre (id) on delete cascade,
    oeuvre_id    bigint  not null references sourcing.oeuvre (id) on delete cascade,
    note         integer,
    titre        text,
    texte        text,
    reponse_a    bigint  references membre.avis (id) on delete set null,
    valide       boolean not null default true,
    creation     timestamptz,
    derniere_maj timestamptz
);

create index avis_oeuvre_idx on membre.avis (oeuvre_id);
create index avis_membre_idx on membre.avis (membre_id);
