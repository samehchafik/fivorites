-- La projection de navigation : une ligne plate par œuvre collectée.
--
-- Pourquoi une vue matérialisée plutôt qu'une lecture directe du brut.
--
-- La grille de cartes se trie « de la plus récente à la plus ancienne ». Cette
-- date vit dans `raw_source.payload`, un jsonb TOAST-é de plusieurs centaines
-- de kilooctets par série. Trier 228 000 séries sur un champ de payload
-- imposerait de décompresser 228 000 payloads **à chaque page** — plusieurs
-- dizaines de gigaoctets lus pour afficher vingt-quatre vignettes.
--
-- Ici les champs de vignette sont extraits une fois, indexés, et la grille ne
-- lit plus que quelques centaines d'octets par ligne. La contrepartie est
-- assumée : la projection est en retard sur le brut jusqu'au prochain
-- `refresh materialized view` — d'où `fiv-admin catalog refresh` et le bouton
-- correspondant dans le front. Le détail d'une œuvre, lui, relit toujours le
-- brut : la fiche qu'on ouvre n'est jamais périmée.
--
-- `distinct on (source_id)` : le brut est append-only et garde l'historique des
-- versions. La vignette montre la dernière.

create materialized view admin.tv_card as
select distinct on (r.source_id)
    r.source_id::int                                   as id,
    r.fetched_at,
    r.payload ->> 'name'                               as name,
    r.payload ->> 'original_name'                      as original_name,
    r.payload ->> 'overview'                           as overview,
    r.payload ->> 'poster_path'                        as poster_path,
    r.payload ->> 'backdrop_path'                      as backdrop_path,
    r.payload ->> 'status'                             as status,
    r.payload ->> 'original_language'                  as original_language,
    -- TMDB renvoie parfois une chaîne vide plutôt qu'une absence de date.
    nullif(r.payload ->> 'first_air_date', '')::date   as first_air_date,
    nullif(r.payload ->> 'last_air_date', '')::date    as last_air_date,
    nullif(r.payload ->> 'number_of_seasons', '')::int as number_of_seasons,
    nullif(r.payload ->> 'number_of_episodes', '')::int as number_of_episodes,
    nullif(r.payload ->> 'vote_average', '')::real     as vote_average,
    nullif(r.payload ->> 'vote_count', '')::int        as vote_count,
    coalesce(r.payload -> 'genres', '[]'::jsonb)       as genres,
    coalesce(r.payload -> 'origin_country', '[]'::jsonb) as origin_country
from sourcing.raw_source r
where r.source = 'tmdb'
  and r.kind = 'tv'
  and r.http_status between 200 and 299
  and r.payload is not null
order by r.source_id, r.fetched_at desc;

comment on materialized view admin.tv_card is
    'Vignettes de navigation, extraites du dernier brut de chaque série. Rafraîchie par `fiv-admin catalog refresh`, jamais écrite à la main.';

-- Unique : c'est la condition d'un `refresh ... concurrently`, donc d'un
-- rafraîchissement qui ne bloque pas les lecteurs pendant qu'il tourne.
create unique index tv_card_id_idx on admin.tv_card (id);

-- Le tri par défaut de la grille.
create index tv_card_air_date_idx on admin.tv_card (first_air_date desc nulls last, id);
create index tv_card_name_idx on admin.tv_card (name);
