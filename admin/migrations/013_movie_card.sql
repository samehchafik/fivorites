-- La projection de navigation des films, pendant exact de `admin.tv_card`.
--
-- Sans elle, la grille de l'administration n'a rien à lire : la collecte des
-- films peut avoir rempli `sourcing.raw_source` de centaines de milliers de
-- fiches, l'écran reste vide. C'est ce qui s'est passé le 2026-08-12 — les
-- films étaient en base, invisibles autrement qu'en SQL.
--
-- Les raisons d'une vue matérialisée sont celles de `002_admin_cards.sql`, et
-- elles pèsent plus lourd encore ici : le catalogue des films compte 1 231 681
-- entrées contre 228 953 séries, et trier sur un champ de payload TOAST-é
-- imposerait de décompresser autant de documents à chaque page.
--
-- LES COLONNES SONT CELLES DE `tv_card`, NOM POUR NOM. Ce n'est pas une
-- coquetterie : c'est ce qui permet à `fetch_cards` de ne changer que le nom
-- de la vue plutôt que d'entretenir deux requêtes de deux cents lignes qui
-- divergeraient au premier tri ajouté. Là où TMDB nomme les choses autrement,
-- c'est ici que la traduction se fait, une fois :
--
--   title            → name              (`name` est le titre d'une série)
--   original_title   → original_name
--   release_date     → first_air_date    (la date de mise à disposition)
--   —                → last_air_date     (null : un film n'a pas de fin de diffusion)
--   —                → number_of_seasons, number_of_episodes (null)
--
-- Et `runtime` n'a pas d'équivalent série : la colonne existe, elle attend que
-- la vignette sache l'afficher. Une durée est au film ce que le nombre de
-- saisons est à la série.

create materialized view admin.movie_card as
select distinct on (r.source_id)
    r.source_id::int                                   as id,
    r.fetched_at,
    r.payload ->> 'title'                              as name,
    r.payload ->> 'original_title'                     as original_name,
    r.payload ->> 'overview'                           as overview,
    r.payload ->> 'poster_path'                        as poster_path,
    r.payload ->> 'backdrop_path'                      as backdrop_path,
    r.payload ->> 'status'                             as status,
    r.payload ->> 'original_language'                  as original_language,
    -- TMDB renvoie parfois une chaîne vide plutôt qu'une absence de date.
    nullif(r.payload ->> 'release_date', '')::date     as first_air_date,
    null::date                                         as last_air_date,
    null::int                                          as number_of_seasons,
    null::int                                          as number_of_episodes,
    nullif(r.payload ->> 'runtime', '')::int           as runtime,
    nullif(r.payload ->> 'vote_average', '')::real     as vote_average,
    nullif(r.payload ->> 'vote_count', '')::int        as vote_count,
    coalesce(r.payload -> 'genres', '[]'::jsonb)       as genres,
    -- Un film n'a pas d'`origin_country` : la donnée équivalente est le code
    -- pays de ses sociétés de production. On la projette sous le même nom pour
    -- que les filtres et l'affichage n'aient pas à savoir lequel des deux ils
    -- lisent.
    coalesce(
        (select jsonb_agg(pays ->> 'iso_3166_1')
         from jsonb_array_elements(coalesce(r.payload -> 'production_countries', '[]'::jsonb)) pays
         where pays ->> 'iso_3166_1' is not null),
        '[]'::jsonb
    )                                                  as origin_country
from sourcing.raw_source r
where r.source = 'tmdb'
  and r.kind = 'movie'
  and r.http_status between 200 and 299
  and r.payload is not null
order by r.source_id, r.fetched_at desc;

comment on materialized view admin.movie_card is
    'Vignettes de navigation des films, extraites du dernier brut de chaque fiche. '
    'Mêmes colonnes que `admin.tv_card`, pour que la grille n''ait qu''une requête.';

-- L'index unique est ce qui autorise `refresh materialized view concurrently`,
-- donc un rafraîchissement qui ne bloque pas la consultation. Sans lui, chaque
-- `catalog refresh` prendrait un verrou exclusif sur la vue — sur un million de
-- films, ce n'est pas une seconde d'attente.
create unique index movie_card_id_idx on admin.movie_card (id);

-- Les mêmes index que la grille des séries, aux mêmes fins : le tri par défaut
-- et la recherche par titre.
create index movie_card_air_date_idx on admin.movie_card (first_air_date desc nulls last, id);
create index movie_card_name_idx on admin.movie_card (name);
