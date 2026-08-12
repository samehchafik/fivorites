-- La couche 2 désigne ses œuvres par le pivot, plus par leur identifiant TMDB.
--
-- Suite directe de `sourcing/012_univers.sql`, qui a rendu `tmdb_catalog`
-- multi-univers et retiré au passage les clés étrangères de ce schéma — parce
-- qu'on ne change pas une clé primaire sous des contraintes qui la visent.
-- Elles sont rétablies ici, sur `sourcing.oeuvre`.
--
-- Ce que ça change pour la lecture : une note ne dit plus « la série TMDB
-- 1399 vaut 8 en action », elle dit « l'œuvre 4212 vaut 8 en action », et
-- c'est le pivot qui sait que cette œuvre est la série TMDB 1399 — ou le film
-- TMDB 1399, ou une série khaleeji que TMDB ne connaît pas. La couche 2 cesse
-- d'avoir un avis sur la provenance des œuvres qu'elle note, ce qui n'a jamais
-- été son travail.
--
-- Le journal reste intact : `training_run` garde ses essais, `score` ses
-- notes, aucune ligne n'est perdue ni réécrite — seule la colonne qui désigne
-- l'œuvre change de nom et de cible.

do $$
begin
    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'sourcing' and table_name = 'tmdb_catalog'
          and column_name = 'univers'
    ) then
        raise exception
            'migration sourcing/012_univers absente — appliquer d''abord `fiv-sourcing db migrate`';
    end if;
end
$$;


-- ---------------------------------------------------------------------------
-- Le passage au pivot, table par table. Même geste chaque fois : une colonne,
-- un report, un contrôle, puis l'ancienne colonne s'en va.
--
-- Le contrôle n'est pas décoratif. `set not null` échouerait de toute façon,
-- mais sur « la colonne oeuvre_id contient des null » — un message qui ne dit
-- ni quelle table ni quelle œuvre. Ici on nomme le nombre de lignes orphelines
-- et la table, ce qui suffit à retrouver la cause (une œuvre notée dont la
-- fiche n'a jamais été collectée avec succès).

do $$
declare
    cible    text;
    orphelins bigint;
begin
    foreach cible in array array['score', 'training_run', 'media_caption', 'embedding']
    loop
        execute format('alter table notation.%I add column oeuvre_id bigint', cible);
        execute format(
            'update notation.%I t set oeuvre_id = o.id
             from sourcing.oeuvre o
             where o.univers = ''series'' and o.id_tmdb = t.id_tmdb', cible
        );
        execute format(
            'select count(*) from notation.%I where oeuvre_id is null', cible
        ) into orphelins;
        if orphelins > 0 then
            raise exception
                '% ligne(s) de notation.% sans pivot — sourcing/012 n''a pas créé leur œuvre',
                orphelins, cible;
        end if;
        execute format(
            'alter table notation.%I
                alter column oeuvre_id set not null,
                add constraint %I foreign key (oeuvre_id)
                    references sourcing.oeuvre (id) on delete cascade,
                drop column id_tmdb', cible, cible || '_oeuvre_fkey'
        );
    end loop;
end
$$;


-- ---------------------------------------------------------------------------
-- Les index et la clé de `media_caption`, refaits à l'identique sur le pivot.
-- Ceux qui portaient `id_tmdb` en tête sont partis avec la colonne.

-- La lecture courante : « les dernières notes de cette œuvre ».
create index score_courant_idx
    on notation.score (oeuvre_id, axe, modele, scored_at desc);

-- L'entraînement des poids : « toutes les notes de ce barème et de ce modèle ».
create index score_entrainement_idx
    on notation.score (rubric_version, modele, oeuvre_id);

-- « Les essais de cette œuvre, du plus récent au plus ancien » — la lecture de
-- la page Training 1.
create index training_run_work_idx on notation.training_run (oeuvre_id, created_at desc);

-- Une légende par (œuvre, url), figée : c'est ce qui garde l'empreinte sha256
-- du dossier stable d'une notation à l'autre.
alter table notation.media_caption add primary key (oeuvre_id, url);

-- Un vecteur par (œuvre, texte soumis, encodeur). Le sha de l'entrée reste
-- dans la clé : si le dossier change, le vecteur est recalculé, jamais
-- réutilisé à tort.
alter table notation.embedding add primary key (oeuvre_id, input_sha256, embedder);

comment on column notation.score.oeuvre_id is
    'Le pivot `sourcing.oeuvre`. Une note ne connaît plus la provenance de l''œuvre qu''elle porte.';
comment on column notation.training_run.oeuvre_id is
    'Le pivot. Le journal traverse les univers sans changer de forme.';
comment on column notation.media_caption.oeuvre_id is
    'Le pivot, comme partout dans `notation`.';
