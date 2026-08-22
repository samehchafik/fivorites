-- La vignette des livres gagne sa popularité.
--
-- Les autres univers tiennent la leur de l'export quotidien TMDB
-- (`tmdb_catalog.popularity`), que la grille lit par jointure. Les livres
-- n'ont pas d'inventaire — il n'y a pas de TMDB du livre — et la colonne
-- restait donc vide : le tri « Popularité » ne classait rien, et le filtre
-- « popularité minimale » écartait tout.
--
-- Le proxy est le **nombre de Wikipédias qui consacrent un article à
-- l'œuvre** (`wikibase:sitelinks`). Ce n'est pas un choix par défaut : c'est
-- déjà l'ordre dans lequel le crawler fait entrer les livres, il est gratuit
-- (un attribut de l'item Wikidata), et il est cross-lingue là où le nombre
-- d'éditions Open Library penche lourdement vers l'anglais et l'ancien.
--
-- L'échelle n'est pas celle de TMDB — quelques unités à deux cents, contre
-- des centaines chez TMDB — et c'est sans conséquence : la grille ne compare
-- jamais deux univers, elle trie à l'intérieur d'un seul.
--
-- Le dump Open Library (lot 2) donnera de quoi l'affiner ; d'ici là, mieux
-- vaut un proxy explicable qu'une colonne vide.

drop materialized view admin.livre_card;

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
       -- La première couverture Open Library du work — une URL complète.
       (select image ->> 'url'
        from jsonb_array_elements(coalesce(ol.media, '[]'::jsonb)) image
        where image ->> 'type' = 'poster'
        limit 1)                                           as poster_path,
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
       coalesce(wd.facts -> 'pays', '[]'::jsonb)           as origin_country,
       -- La langue d'origine + les langues d'édition. C'est ce que le
       -- sélecteur de langue filtre : « sur Français, des livres français ou
       -- traduits en français » — une carte dont le lecteur ne peut rien
       -- lire n'a rien à faire dans sa grille.
       (select coalesce(jsonb_agg(distinct langue), '[]'::jsonb)
        from (
            select jsonb_array_elements_text(
                coalesce(wd.facts -> 'langues', '[]'::jsonb)) as langue
            union
            select e ->> 'langue'
            from jsonb_array_elements(
                coalesce(ol.facts -> 'editions' -> 'par_langue', '[]'::jsonb)) e
        ) l
        where langue is not null)                           as langues,
       (wd.facts ->> 'sitelinks')::real                     as popularity
from sourcing.oeuvre o
left join lateral (
    select r.facts, r.fetched_at
    from sourcing.riche_source r
    where r.oeuvre_id = o.id and r.source = 'wikidata'
    limit 1
) wd on true
left join lateral (
    select r.facts, r.content, r.media, r.fetched_at
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
    'il n''y a pas de TMDB du livre. poster_path est une URL complète '
    '(couverture Open Library) et popularity le nombre de Wikipédias qui '
    'portent l''œuvre. Mêmes colonnes que admin.tv_card, plus langues.';

create unique index livre_card_id_idx on admin.livre_card (id);
create index livre_card_air_date_idx on admin.livre_card (first_air_date desc nulls last, id);
create index livre_card_name_idx on admin.livre_card (name);
-- Le tri « Popularité » de la grille, et le filtre qui l'accompagne.
create index livre_card_popularity_idx on admin.livre_card (popularity desc nulls last, id);
