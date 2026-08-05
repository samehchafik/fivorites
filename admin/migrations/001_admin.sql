-- Schéma `admin` : les comptes du front d'administration.
--
-- Une seule base pour tout le projet, un schéma par domaine — même règle que
-- `sourcing`. Ce schéma ne contient que ce qui appartient en propre à
-- l'administration : les comptes. Tout ce qu'affiche le front est lu dans
-- `sourcing`, jamais copié ici.
--
-- L'historique des migrations reste dans `public.schema_migrations`, partagé
-- avec `sourcing` : les noms de fichiers étant distincts (`001_admin` contre
-- `001_sourcing`), les deux jeux cohabitent sans collision.

create schema if not exists admin;


create table admin.admin_user (
    username      text        primary key,
    password_hash text        not null,   -- scrypt$n$r$p$sel$empreinte, voir security.py
    display_name  text,
    disabled      boolean     not null default false,
    created_at    timestamptz not null default now(),
    last_login_at timestamptz
);

comment on table admin.admin_user is
    'Comptes du front d''administration. Créés en ligne de commande (`fiv-admin user add`), jamais par le front : il n''y a pas d''inscription.';
comment on column admin.admin_user.password_hash is
    'scrypt, sel aléatoire par compte. Le mot de passe en clair n''existe nulle part.';


-- Les index de lecture du front. Ils portent sur `sourcing.raw_source`, mais
-- ils appartiennent à l'administration : c'est elle seule qui pose ces
-- questions-là, et la collecte n'a pas à payer leur maintenance sans savoir
-- pourquoi. Les mettre ici les rend réversibles avec le front.
--
-- 1. « quelles saisons de la série 1399, dans quelle langue ? » — l'id de série
--    est le préfixe de `source_id` ('1399/s2'), d'où l'index sur l'expression.
--    Sans lui, chaque ligne du tableau coûterait un parcours complet.
do $$
begin
    if not exists (select 1 from information_schema.schemata where schema_name = 'sourcing') then
        raise exception 'schéma sourcing absent — appliquer d''abord les migrations de sourcing/';
    end if;
end
$$;

create index if not exists raw_source_series_lang_idx
    on sourcing.raw_source (source, kind, (split_part(source_id, '/', 1)), lang);

-- 2. « combien de lignes par langue ? » — les compteurs de l'en-tête, en
--    parcours d'index seul plutôt qu'en parcours de table.
create index if not exists raw_source_lang_count_idx
    on sourcing.raw_source (source, kind, lang);

-- 3. le dénominateur de la couverture — « combien de saisons cette série
--    a-t-elle, d'après ce que la collecte a énuméré ». `fetch_state` porte une
--    ligne par saison, succès ou échec ; sa clé primaire commence par `source`
--    et `kind`, mais ne sait pas retrouver un préfixe de `source_id`.
create index if not exists fetch_state_series_idx
    on sourcing.fetch_state (source, kind, (split_part(source_id, '/', 1)));

-- 4. le tri « dernière collecte » du tableau.
create index if not exists fetch_state_recent_idx
    on sourcing.fetch_state (source, kind, last_fetched_at desc);
