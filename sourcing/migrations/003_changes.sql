-- Détection des modifications côté TMDB.
--
-- Trois questions distinctes, trois mécanismes :
--
--   « quelles séries sont nouvelles ? »   → absentes de tmdb_catalog, apportées
--                                            par l'export quotidien
--   « lesquelles ont disparu ? »          → exported_on qui décroche
--   « lesquelles ont changé ? »           → cette colonne
--
-- La V1 ne savait répondre à aucune des trois : son incrémental reposait sur un
-- dictionnaire `{id: true}` sans horodatage, donc « déjà vu » était la seule
-- information disponible.

alter table sourcing.tmdb_catalog
    add column changed_at timestamptz;

comment on column sourcing.tmdb_catalog.changed_at is
    'Dernière modification signalée par /tv/changes. Comparée à fetch_state.last_success_at, '
    'elle dit si notre copie est périmée — sans avoir à retélécharger pour le découvrir.';

-- La sélection du backfill ne consulte que les séries signalées : index partiel,
-- il ne porte que sur elles.
create index tmdb_catalog_changed_idx
    on sourcing.tmdb_catalog (changed_at)
    where changed_at is not null;
