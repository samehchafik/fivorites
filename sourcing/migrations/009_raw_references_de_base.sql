-- `raw_source` ne porte plus que les références de base des séries.
--
-- R1 du 2026-08-07 (`doc/architecture-sourcing.md`) : deux choses seulement —
-- la collecte TMDB, et la référence Wikidata des séries hors TMDB (la ligne
-- par QID du crawler, leur fiche d'identité). L'enrichissement, lui, n'écrit
-- jamais dans le brut : ce qu'il apporte vit dans `riche_source`, sous forme
-- interprétée et homogène.
--
-- Cette migration purge ce que les versions précédentes de `enrich` y avaient
-- écrit : les articles Wikipédia, les entités Wikidata, et les lookups des
-- séries TMDB (source_id numérique — ceux des séries hors TMDB, keyés par
-- QID, sont les références de base et restent).
--
-- Rien n'est perdu pour l'usage : le texte et les faits de ces réponses sont
-- dans `riche_source`. Ce qui est perdu, et assumé, c'est la possibilité de
-- rejouer l'extraction hors ligne — rejouer = réinterroger (R4).

delete from sourcing.raw_source
where source = 'wikipedia';

delete from sourcing.raw_source
where source = 'wikidata' and kind = 'entity';

delete from sourcing.raw_source
where source = 'wikidata' and kind = 'lookup'
  and source_id ~ '^[0-9]+$';

-- L'état de reprise des articles n'a plus d'objet — c'est le lookup de la
-- série qui porte la reprise de l'enrichissement, pour les deux flux.
delete from sourcing.fetch_state
where source = 'wikipedia';
