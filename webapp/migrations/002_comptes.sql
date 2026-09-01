-- Les comptes du site public, et les fives — la raison d'être du produit.
--
-- Le compte vit dans le schéma `visiteur`, à côté de la session anonyme,
-- parce que c'est la MÊME personne à deux moments de sa vie : elle classe
-- d'abord sans s'inscrire, puis se crée un compte — et la colonne
-- `compte_id` de la session, prévue dès la migration 001, rattache tout ce
-- qu'elle avait déjà classé. Rien ne se perd à l'inscription.
--
-- `membre.*` (l'import V1) reste en lecture seule : les nouveaux comptes ne
-- s'y mélangent pas — les fives d'ici rejoindront le graphe par leur propre
-- projection, comme celles de la V1 par la leur.

create table visiteur.compte (
    id               uuid        primary key default gen_random_uuid(),
    pseudo           text        not null check (length(pseudo) between 2 and 40),
    -- L'adresse, en minuscules dès l'écriture : l'unicité doit ignorer la
    -- casse, et la normaliser à l'entrée vaut mieux qu'un index expression
    -- que chaque requête devrait connaître.
    email            text        not null unique check (email = lower(email)),
    -- scrypt (hashlib, rien à installer), au format
    -- scrypt$n$r$p$sel$empreinte — le format se lit dans la colonne.
    mot_de_passe     text        not null,
    -- Falcultatif et déclaratif, comme demandé.
    genre            text        check (genre in ('fille', 'garcon')),
    email_verifie_le timestamptz,
    creation         timestamptz not null default now()
);

comment on table visiteur.compte is
    'Un compte du site public : pseudo, email vérifié par code, mot de '
    'passe scrypt. Tant que email_verifie_le est nul, le compte ne peut '
    'rien faire.';

-- Le code de vérification : UN par compte — un renvoi remplace l'ancien.
create table visiteur.verification (
    compte_id  uuid        primary key references visiteur.compte (id) on delete cascade,
    code       text        not null check (code ~ '^[0-9]{6}$'),
    expire_le  timestamptz not null,
    -- Compté pour fermer la porte à l'énumération : au-delà du plafond, il
    -- faut demander un nouveau code.
    tentatives int         not null default 0,
    envoye_le  timestamptz not null default now()
);

-- La session anonyme se rattache au compte à la connexion : les classements
-- déjà faits deviennent ceux du compte, comme promis en 001.
alter table visiteur.session
    add column compte_id uuid references visiteur.compte (id) on delete set null;

create index session_compte_idx on visiteur.session (compte_id)
    where compte_id is not null;

-- Les fives : LE geste fondateur — vos cinq meilleures œuvres, par univers,
-- rang 1 à 5. Une œuvre ne peut occuper qu'un rang (l'unicité le garantit),
-- et changer d'avis est un UPDATE du rang, pas un doublon.
create table visiteur.five (
    compte_id uuid        not null references visiteur.compte (id) on delete cascade,
    univers   text        not null,
    rang      int         not null check (rang between 1 and 5),
    oeuvre_id bigint      not null references sourcing.oeuvre (id) on delete cascade,
    creation  timestamptz not null default now(),
    primary key (compte_id, univers, rang),
    unique (compte_id, univers, oeuvre_id)
);

comment on table visiteur.five is
    'Les cinq meilleures œuvres d''un compte, par univers — le cœur du '
    'produit, et la graine la plus forte des suggestions.';
