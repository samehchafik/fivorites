-- La date de première diffusion, dénormalisée dans l'inventaire.
--
-- Elle n'est pas dans l'export quotidien de TMDB, qui ne porte que l'id, le
-- titre original, la popularité et le drapeau adulte. Elle vit dans le payload
-- de la fiche, donc dans `raw_source`.
--
-- Pourquoi la recopier ici plutôt que de la lire là-bas : trier 228 000 séries
-- sur un champ d'un `jsonb` de plusieurs centaines de kilooctets décompresse
-- toute la table. C'est le même coût qui a justifié la projection
-- `admin.tv_card` côté administration — la différence est qu'ici on n'a besoin
-- que d'une date, pas d'une vue entière.
--
-- C'est donc une **dérivation**, au même titre que `series_source` : elle se
-- reconstruit depuis `raw_source` sans réseau, par `tmdb dates`.

alter table sourcing.tmdb_catalog
    add column first_air_date date;

comment on column sourcing.tmdb_catalog.first_air_date is
    'Dérivée de raw_source par `tmdb dates`. Null tant que la série n''est pas collectée.';

-- L'ordre « les plus récentes, et à date égale les plus populaires ».
--
-- `nulls last` n'est pas un détail : les séries non encore collectées n'ont pas
-- de date, et ce sont aussi celles pour lesquelles l'enrichissement a le moins
-- de prise — sans `imdb_id` collecté, l'appariement TVmaze ne peut rien
-- confirmer. Les traiter en dernier est donc doublement justifié.
create index tmdb_catalog_recent_idx
    on sourcing.tmdb_catalog (first_air_date desc nulls last, popularity desc);
