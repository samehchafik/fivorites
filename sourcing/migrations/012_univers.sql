-- L'univers entre dans l'identité, et le pivot devient la clé.
--
-- LE FAIT QUI COMMANDE TOUT : les identifiants TMDB de films et de séries
-- vivent dans deux espaces de noms disjoints. `1399` désigne Game of Thrones
-- côté /tv et un tout autre film côté /movie. Or `tmdb_catalog` a `id` seul
-- pour clé primaire, et `load_catalog` charge l'export par
-- `on conflict (id) do update` : le premier `tmdb export --univers movies`
-- écraserait 228 953 lignes de séries par des films portant les mêmes
-- numéros. Sans erreur, sans avertissement, et sans retour en arrière — le
-- titre original et la popularité de la série seraient perdus.
--
-- D'où cette migration, qui est le préalable de toute collecte de films et
-- ne collecte aucun film. Elle se joue entièrement sur les séries.
--
-- DEUX CHANGEMENTS, ET LE SECOND EST LE VRAI.
--
-- 1. `tmdb_catalog` prend une colonne `univers` et une clé primaire qui la
--    porte. C'est la correction mécanique.
--
-- 2. Les tables de la couche 2 cessent de désigner les œuvres par leur
--    identifiant TMDB et passent au pivot `sourcing.oeuvre`. C'est la
--    correction de fond, et elle était écrite d'avance : la migration 007 qui
--    a créé `oeuvre` annonçait « c'est aussi, par anticipation, l'`oeuvre_id`
--    que la couche 2 (notation) attend ».
--
-- Pourquoi le pivot plutôt qu'une clé composite `(univers, id_tmdb)` partout :
-- parce que la clé composite ne résout que la collision, alors que le pivot
-- résout aussi le cas qui l'a fait naître — une œuvre sans identifiant TMDB.
-- 300 des 480 séries de langue arabe n'ont aucun identifiant externe ; aucune
-- ne peut être notée tant que la note se range sous un `id_tmdb`. Le film
-- khaleeji posera la même question, et la poserait après coup.
--
-- Ce que cette migration ne fait pas, volontairement : renommer
-- `original_name` en `titre_original` ni `first_air_date` en `date_sortie`.
-- L'export film porte bien d'autres noms de champs (`original_title`), mais
-- c'est le travail du lot de collecte — mélanger les deux rendrait celui-ci
-- illisible.


-- ---------------------------------------------------------------------------
-- 1. L'inventaire TMDB devient multi-univers.

alter table sourcing.tmdb_catalog
    add column univers text not null default 'series';

comment on column sourcing.tmdb_catalog.univers is
    'series | movies. Le même entier désigne deux œuvres différentes selon l''univers : '
    'il ne suffit pas à identifier une ligne, et ne l''a jamais suffi.';

-- Les clés étrangères qui visent `tmdb_catalog (id)` interdisent d'en changer
-- la primaire. On les retire toutes.
--
-- Le parcours est dirigé par le catalogue système plutôt que par une liste
-- écrite à la main, pour deux raisons. Une FK oubliée ferait échouer la
-- migration à mi-parcours, sur un message qui ne dirait pas laquelle. Et
-- surtout, certaines de ces contraintes appartiennent au schéma `notation`,
-- créé par les migrations de l'admin — qui peuvent ne pas être passées ici
-- (c'est le cas de la base de test de `sourcing`). Une liste en dur devrait
-- deviner ce qui existe ; ce parcours le lit.
--
-- Celles de `notation` sont rétablies sur le pivot par la migration 012 de
-- l'admin, qui refuse de s'appliquer si celle-ci ne l'a pas été.
--
-- Une seule n'est pas rétablie du tout, et c'est voulu : `riche_source.id_tmdb`.
-- La migration 007 l'a documentée comme « redondante avec oeuvre.id_tmdb,
-- gardée pour les jointures directes » — l'intégrité de cette table passe par
-- `oeuvre_id`, qui garde la sienne. Lui rendre une clé composite demanderait
-- d'y ajouter une colonne `univers` que le pivot porte déjà.
do $$
declare contrainte record;
begin
    for contrainte in
        select conrelid::regclass::text as table_source, conname as nom
        from pg_constraint
        where confrelid = 'sourcing.tmdb_catalog'::regclass and contype = 'f'
    loop
        execute format(
            'alter table %s drop constraint %I', contrainte.table_source, contrainte.nom
        );
        raise notice 'clé étrangère retirée : %  (%)', contrainte.table_source, contrainte.nom;
    end loop;
end
$$;

alter table sourcing.tmdb_catalog
    drop constraint tmdb_catalog_pkey,
    add primary key (univers, id);


-- ---------------------------------------------------------------------------
-- 2. Le pivot, pour toutes les œuvres déjà collectées.
--
-- `oeuvre` était jusqu'ici créée paresseusement, à l'enrichissement : inutile
-- de fabriquer 228 000 lignes pour un catalogue dont la plus grande part
-- n'aura jamais une ligne de `riche_source`. Ce raisonnement tombe dès que la
-- notation désigne ses œuvres par le pivot — une série collectée doit pouvoir
-- être notée sans passer par l'enrichissement.
--
-- La règle devient donc : **une œuvre existe dès que sa fiche a été
-- téléchargée**. La collecte s'en charge désormais (`store.ensure_oeuvres`
-- appelé par `collect_series`) ; ce bloc rattrape l'existant.

with collectees as (
    select distinct source_id::int as id
    from sourcing.raw_source
    where source = 'tmdb' and kind = 'tv'
      and http_status between 200 and 299
      -- Les fiches de série ont un `source_id` numérique ; les saisons portent
      -- la forme `1399/s2` sous un autre `kind`. Le garde-fou coûte moins cher
      -- qu'un cast qui ferait tomber la migration entière sur une ligne.
      and source_id ~ '^\d+$'
)
insert into sourcing.oeuvre (univers, id_tmdb)
select 'series', x.id from collectees x
on conflict do nothing;

-- Le filet : toute œuvre déjà référencée par une table dépendante doit avoir
-- son pivot, qu'elle soit collectée ou non. Sans ce bloc, une ligne de
-- `video` ou de `score` pointant sur une fiche jamais collectée avec succès
-- ferait échouer le `set not null` plus bas — et le message parlerait d'une
-- colonne, pas de la ligne fautive.
do $$
declare source_de_lignes text;
begin
    foreach source_de_lignes in array array[
        'sourcing.video', 'sourcing.video_scan',
        'notation.score', 'notation.training_run', 'notation.media_caption'
    ]
    loop
        if to_regclass(source_de_lignes) is null then
            continue;   -- schéma `notation` absent : base de test de sourcing
        end if;
        execute format(
            'insert into sourcing.oeuvre (univers, id_tmdb)
             select distinct ''series'', t.id_tmdb from %s t
             on conflict do nothing', source_de_lignes
        );
    end loop;
end
$$;

-- Et le pivot ne retrouve PAS sa clé étrangère vers l'inventaire. C'est un
-- choix, pas un oubli.
--
-- `tmdb_catalog` est une base de sondage, pas une source d'identité : elle est
-- alimentée par l'export quotidien, et une série apparaît dans `/tv/changes`
-- — donc peut être collectée — avant d'entrer dans l'export du lendemain.
-- `mark_changed` le dit déjà pour son propre compte : « une série créée
-- aujourd'hui apparaît dans changes avant d'entrer dans l'export quotidien ».
--
-- Tant que l'œuvre naissait à l'enrichissement, qui sélectionne depuis
-- l'inventaire, la contrainte ne se voyait pas. Elle naît maintenant à la
-- collecte, et `fiv-sourcing tmdb fetch --id <nouveauté>` tomberait sur une
-- violation de clé étrangère pour une série parfaitement réelle.
--
-- Faire dépendre l'identité de l'inventaire est de toute façon l'inverse de ce
-- que `oeuvre` existe pour faire : la migration 007 l'a créée précisément pour
-- les œuvres « connues que de Wikidata, que de TVmaze, ou de personne ».
--
-- L'unicité, elle, reste : `oeuvre_tmdb_idx` garantit qu'un identifiant TMDB
-- ne désigne qu'une œuvre par univers, ce qui est la seule garantie utile ici.


-- ---------------------------------------------------------------------------
-- 3. Le canal vidéo passe au pivot.
--
-- Même raisonnement que pour `riche_source` au lot 7 : c'est le pivot qui
-- rassemble les lignes d'une même œuvre. Et la table le demandait déjà — son
-- propre commentaire prévoit des vidéos venues d'un autre fournisseur que
-- TMDB, ce qu'un `id_tmdb` obligatoire rend impossible.

alter table sourcing.video add column oeuvre_id bigint;

update sourcing.video v
set oeuvre_id = o.id
from sourcing.oeuvre o
where o.univers = 'series' and o.id_tmdb = v.id_tmdb;

alter table sourcing.video
    alter column oeuvre_id set not null,
    drop constraint video_pkey,
    add primary key (oeuvre_id, site, cle),
    add constraint video_oeuvre_fkey
        foreign key (oeuvre_id) references sourcing.oeuvre (id) on delete cascade,
    -- L'index de lecture de la fiche portait `id_tmdb` en tête : il disparaît
    -- avec la colonne, et se refait juste après sur le pivot.
    drop column id_tmdb;

create index video_oeuvre_idx
    on sourcing.video (oeuvre_id, priorite, publie_le desc nulls last);

comment on column sourcing.video.oeuvre_id is
    'Le pivot. C''est lui qui attache la vidéo à l''œuvre, y compris quand elle vient '
    'd''un fournisseur qui ne connaît pas TMDB.';


alter table sourcing.video_scan add column oeuvre_id bigint;

update sourcing.video_scan s
set oeuvre_id = o.id
from sourcing.oeuvre o
where o.univers = 'series' and o.id_tmdb = s.id_tmdb;

alter table sourcing.video_scan
    alter column oeuvre_id set not null,
    drop constraint video_scan_pkey,
    add primary key (oeuvre_id),
    add constraint video_scan_oeuvre_fkey
        foreign key (oeuvre_id) references sourcing.oeuvre (id) on delete cascade,
    drop column id_tmdb;

comment on table sourcing.video_scan is
    'Ce que la passe vidéo a déjà examiné — y compris les œuvres sans aucune vidéo.';
