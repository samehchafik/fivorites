-- Les articles Wikipédia du brut, re-keyés par la clé de la série.
--
-- Constaté en production : `raw_source` portait des lignes
-- (wikipedia, article, « Sürekli Dizi: Kayıp Kasetler ») — keyées par le
-- *titre* de l'article, qui dépend de la langue, quand tout le reste du brut
-- est keyé par l'identifiant de la série. Impossible de retrouver les lignes
-- brutes d'une série par une seule clé.
--
-- Désormais `source_id` porte la clé de la série — l'id TMDB au flux 1, le QID
-- au flux 2 — et le titre reste dans le payload et dans
-- `riche_source.source_id`. Cette migration re-keye l'existant en retrouvant la
-- série par jointure sur `riche_source` (même titre, même langue).
--
-- Limites assumées, sur des cas rares :
--   * un article dont le titre canonique diffère du titre demandé (redirection
--     suivie) peut ne pas s'apparier — la ligne garde alors son titre en clé,
--     et le prochain enrichissement (--refresh-after) écrira la version
--     re-keyée ;
--   * deux séries partageant un même article (page de franchise) : la ligne ne
--     peut recevoir qu'une clé, l'appariement prend la première.

with correspondance as (
    select distinct on (r.id)
           r.id as raw_id,
           coalesce(o.id_tmdb::text, o.wikidata_qid) as cle
    from sourcing.raw_source r
    join sourcing.riche_source rs
      on rs.source = 'wikipedia'
     and rs.source_id = r.source_id
     and rs.lang = coalesce(r.lang, '')
    join sourcing.oeuvre o on o.id = rs.oeuvre_id
    where r.source = 'wikipedia' and r.kind = 'article'
      and coalesce(o.id_tmdb::text, o.wikidata_qid) is not null
    order by r.id, o.id
)
update sourcing.raw_source r
set source_id = c.cle
from correspondance c
where r.id = c.raw_id
  and r.source_id <> c.cle;

-- Même chose pour l'état de reprise : une entrée par article, keyée pareil.
-- Les entrées au titre restées sans correspondance sont supprimées plutôt que
-- laissées : fetch_state n'est pas un historique, c'est l'état courant, et une
-- clé morte y bloquerait pour rien la reprise.
with correspondance as (
    select distinct on (f.source_id)
           f.source_id as ancien,
           coalesce(o.id_tmdb::text, o.wikidata_qid) as cle
    from sourcing.fetch_state f
    join sourcing.riche_source rs
      on rs.source = 'wikipedia' and rs.source_id = f.source_id
    join sourcing.oeuvre o on o.id = rs.oeuvre_id
    where f.source = 'wikipedia' and f.kind = 'article'
      and coalesce(o.id_tmdb::text, o.wikidata_qid) is not null
    order by f.source_id, o.id
)
insert into sourcing.fetch_state (source, kind, source_id, last_fetched_at,
                                  last_success_at, last_changed_at, attempts,
                                  last_status, last_error)
select f.source, f.kind, c.cle, f.last_fetched_at, f.last_success_at,
       f.last_changed_at, f.attempts, f.last_status, f.last_error
from sourcing.fetch_state f
join correspondance c on c.ancien = f.source_id
where f.source = 'wikipedia' and f.kind = 'article'
on conflict (source, kind, source_id) do nothing;

delete from sourcing.fetch_state f
where f.source = 'wikipedia' and f.kind = 'article'
  and f.source_id !~ '^[0-9]+$' and f.source_id !~ '^Q[0-9]+$';
