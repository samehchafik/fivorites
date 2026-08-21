-- L'univers livre entre par le pivot — et il apporte son identifiant.
--
-- Il n'y a pas de TMDB du livre (doc/etude-sources-livres.md) : la première
-- référence est Open Library, dont l'identifiant de work (OLID, ex.
-- `OL27258W`) est porté par Wikidata sous P648. Comme tous les identifiants
-- externes du pivot, il est nullable — 23 % seulement des grandes œuvres
-- arabes le portent — et unique par univers : la réconciliation tardive
-- fonctionne comme pour TMDB, c'est la MÊME ligne d'œuvre qui gagne un
-- id_openlibrary le jour où il apparaît.
--
-- Rien d'autre : l'univers `livres` n'a besoin ni d'inventaire (`tmdb_catalog`
-- reste aux univers TMDB — la base de sondage des livres sera le dump Open
-- Library, lot 2) ni de nouvelles tables. `oeuvre`, `raw_source`,
-- `fetch_state` et `riche_source` ont été construits pour accueillir un
-- univers de plus sans changer d'architecture (migration 007).

alter table sourcing.oeuvre
    add column id_openlibrary text;

comment on column sourcing.oeuvre.id_openlibrary is
    'L''identifiant de work Open Library (OLID, ex. OL27258W) — la première '
    'référence de l''univers livres. Null pour les autres univers, et pour les '
    'livres que seul Wikidata connaît.';

create unique index oeuvre_openlibrary_idx
    on sourcing.oeuvre (univers, id_openlibrary)
    where id_openlibrary is not null;
