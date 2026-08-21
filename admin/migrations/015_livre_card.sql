-- La projection de navigation des livres — le troisième pendant de
-- `admin.tv_card`, et le premier qui ne lit pas TMDB.
--
-- LES COLONNES SONT CELLES DE `tv_card`, NOM POUR NOM — même contrat que
-- `013_movie_card.sql` : c'est ce qui permet à `fetch_cards` de ne changer
-- que le nom de la vue. Deux différences de fond avec les deux autres :
--
--   * la clé `id` est le **pivot** `sourcing.oeuvre.id`, pas un identifiant
--     TMDB — il n'y en a pas (`media.pivot_card` le dit aux lecteurs) ;
--   * la matière ne vient pas d'un payload de fiche mais de `riche_source` :
--     le titre d'Open Library, les faits de Wikidata, et l'article Wikipédia
--     comme synopsis — dans l'ordre de préférence fr, en, es, ar, qui est
--     celui des langues cibles du projet.
--
-- Ce qui reste à null l'est honnêtement : un livre n'a ni affiche TMDB, ni
-- statut de diffusion, ni saisons, ni votes. La vignette du front affiche
-- son gabarit sans image, comme pour une série sans `poster_path`.

create materialized view admin.livre_card as
select o.id                                                as id,
       coalesce(ol.fetched_at, wd.fetched_at, o.created_at) as fetched_at,
       -- Le libellé Wikidata d'abord : c'est l'identité de l'œuvre. Le titre
       -- du work Open Library le remplace seulement s'il manque — un
       -- appariement faible (resolved_by = titre) rendrait sinon son bruit
       -- visible en tête de vignette.
       coalesce(o.titre, ol.facts ->> 'titre')             as name,
       o.titre                                             as original_name,
       coalesce(wp.content, ol.content)                    as overview,
       null::text                                          as poster_path,
       null::text                                          as backdrop_path,
       null::text                                          as status,
       wd.facts -> 'langues' ->> 0                         as original_language,
       case when coalesce((wd.facts ->> 'annee')::int, o.annee) is not null
            then make_date(coalesce((wd.facts ->> 'annee')::int, o.annee), 1, 1)
       end                                                 as first_air_date,
       null::date                                          as last_air_date,
       null::int                                           as number_of_seasons,
       null::int                                           as number_of_episodes,
       null::real                                          as vote_average,
       null::int                                           as vote_count,
       '[]'::jsonb                                         as genres,
       coalesce(wd.facts -> 'pays', '[]'::jsonb)           as origin_country
from sourcing.oeuvre o
left join lateral (
    select r.facts, r.fetched_at
    from sourcing.riche_source r
    where r.oeuvre_id = o.id and r.source = 'wikidata'
    limit 1
) wd on true
left join lateral (
    select r.facts, r.content, r.fetched_at
    from sourcing.riche_source r
    where r.oeuvre_id = o.id and r.source = 'openlibrary'
    limit 1
) ol on true
left join lateral (
    select r.content
    from sourcing.riche_source r
    where r.oeuvre_id = o.id and r.source = 'wikipedia'
      and nullif(btrim(r.content), '') is not null
    order by array_position(array['fr', 'en', 'es', 'ar'], r.lang) nulls last,
             r.content_chars desc
    limit 1
) wp on true
where o.univers = 'livres';

comment on materialized view admin.livre_card is
    'Vignettes de navigation des livres, assemblées depuis riche_source '
    '(Wikidata, Open Library, Wikipédia). Clé = le pivot sourcing.oeuvre.id — '
    'il n''y a pas de TMDB du livre. Mêmes colonnes que admin.tv_card.';

-- Même trio d'index que les deux autres projections, aux mêmes fins :
-- l'unique autorise `refresh materialized view concurrently`, les deux autres
-- portent le tri par défaut et la recherche par titre.
create unique index livre_card_id_idx on admin.livre_card (id);
create index livre_card_air_date_idx on admin.livre_card (first_air_date desc nulls last, id);
create index livre_card_name_idx on admin.livre_card (name);
