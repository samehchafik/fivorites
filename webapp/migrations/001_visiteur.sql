-- Le schéma du site public : la session anonyme et ses signaux de goût.
--
-- C'est la première écriture « produit » de la V2 — tout ce qui existait
-- jusqu'ici (membre.five, membre.avis) est importé de la V1 et servi en
-- lecture seule. Le choix de démarrage est la session anonyme : l'outil de
-- suggestion marche sans inscription, un cookie signé porte l'identifiant de
-- session, et les signaux vivent côté serveur — c'est eux que la
-- recommandation lit. Le jour des vrais comptes, une colonne `membre_id`
-- nullable suffira à rattacher une session à un membre sans rien perdre.
--
-- Le schéma s'appelle `visiteur` et pas `webapp` : il nomme ce qu'il
-- contient (qui est ce visiteur, qu'a-t-il classé), pas le service qui
-- l'écrit — même logique que `membre` et `notation`.

create schema if not exists visiteur;

create table visiteur.session (
    id                uuid        primary key default gen_random_uuid(),
    creation          timestamptz not null default now(),
    derniere_activite timestamptz not null default now()
);

comment on table visiteur.session is
    'Une session anonyme du site public. Aucune donnée personnelle : '
    'l''identifiant vit dans un cookie signé, et c''est tout ce qu''on sait.';

-- Un signal par (session, œuvre) : les trois statuts sont exclusifs — on ne
-- peut pas à la fois avoir aimé et vouloir voir — et reclasser une œuvre est
-- un UPDATE, pas un doublon. La clé le garantit.
--
-- `oeuvre_id` est le pivot `sourcing.oeuvre.id`, jamais un identifiant TMDB :
-- c'est la seule identité commune aux trois univers, et c'est celle que le
-- graphe Neo4j porte (`FivOeuvre.oeuvreId`) — le signal est fait pour lui.
create table visiteur.signal (
    session_id uuid        not null references visiteur.session (id) on delete cascade,
    oeuvre_id  bigint      not null references sourcing.oeuvre (id) on delete cascade,
    univers    text        not null,
    statut     text        not null check (statut in ('aime', 'aime_pas', 'a_voir')),
    creation   timestamptz not null default now(),
    primary key (session_id, oeuvre_id)
);

comment on table visiteur.signal is
    'Ce qu''un visiteur a classé : j''ai vu et aimé (aime), je n''aime pas '
    '(aime_pas), je veux voir (a_voir). La matière première des suggestions.';

-- La lecture du service est toujours « les signaux d'une session », souvent
-- filtrés par statut : la clé primaire couvre la première, cet index la
-- seconde.
create index signal_session_statut_idx on visiteur.signal (session_id, statut);
