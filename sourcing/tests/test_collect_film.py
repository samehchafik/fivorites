"""La collecte d'un film, de bout en bout. TMDB est simulé.

Ce qui distingue un film d'une série tient en trois faits, et ce fichier les
vérifie un par un : une seule requête, un `kind` à `movie`, et le pivot rangé
sous l'univers `movies` — celui-là même qui permet au film 1399 de cohabiter
avec *Game of Thrones*.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from fiv_sourcing.config import Settings
from fiv_sourcing.sources.tmdb.client import MOVIE_APPEND, SERIES_APPEND, TmdbClient, build_fetcher
from fiv_sourcing.sources.tmdb.collect import collect, collect_movie
from fiv_sourcing.univers import FILMS

pytestmark = pytest.mark.integration

FILM = {
    "id": 550,
    "title": "Fight Club",
    "original_title": "Fight Club",
    "release_date": "1999-10-15",
    "runtime": 139,
    "tagline": "Mischief. Mayhem. Soap.",
    "imdb_id": "tt0137523",
    "belongs_to_collection": None,
}


@respx.mock
async def test_un_film_tient_en_une_requete(conn, settings: Settings) -> None:
    """L'écart de coût qui rend l'univers film abordable : une série demande sa
    fiche plus chaque saison dans chaque langue — une quarantaine d'appels pour
    un feuilleton ordinaire — là où un film en demande un."""
    route = respx.get(url__startswith="https://api.themoviedb.org/3/movie/550").mock(
        httpx.Response(200, json=FILM)
    )
    fetcher = build_fetcher(settings)
    async with fetcher:
        report = await collect_movie(conn, TmdbClient(fetcher, settings), 550)

    assert report.ok
    assert report.requests == 1
    assert report.rows_written == 1
    assert route.call_count == 1

    async with conn.cursor() as cur:
        await cur.execute("select kind, source_id, lang from raw_source")
        assert await cur.fetchall() == [("movie", "550", "fr-FR")]


@respx.mock
async def test_le_film_range_son_pivot_dans_l_univers_films(conn, settings: Settings) -> None:
    """Le point qui justifie tout le lot 12 : le pivot d'un film ne doit pas
    pouvoir être confondu avec celui de la série de même numéro."""
    respx.get(url__startswith="https://api.themoviedb.org/3/movie/1399").mock(
        httpx.Response(200, json={"id": 1399, "title": "Un film"})
    )
    respx.get(url__startswith="https://api.themoviedb.org/3/tv/1399").mock(
        httpx.Response(200, json={"id": 1399, "name": "Game of Thrones", "seasons": []})
    )

    fetcher = build_fetcher(settings)
    async with fetcher:
        client = TmdbClient(fetcher, settings)
        await collect(conn, client, 1399, FILMS)
        await collect(conn, client, 1399)  # séries, par défaut

    async with conn.cursor() as cur:
        await cur.execute("select univers, id_tmdb from oeuvre order by univers")
        assert await cur.fetchall() == [("movies", 1399), ("series", 1399)], (
            "deux œuvres distinctes sous le même numéro TMDB"
        )
        await cur.execute("select count(distinct id) from oeuvre")
        assert await cur.fetchone() == (2,)


@respx.mock
async def test_un_404_ne_cree_ni_ligne_ni_oeuvre(conn, settings: Settings) -> None:
    respx.get(url__startswith="https://api.themoviedb.org/3/movie/999999").mock(
        httpx.Response(
            404, json={"status_message": "The resource you requested could not be found."}
        )
    )
    fetcher = build_fetcher(settings)
    async with fetcher:
        report = await collect_movie(conn, TmdbClient(fetcher, settings), 999999)

    assert not report.ok
    async with conn.cursor() as cur:
        await cur.execute("select count(*) from oeuvre")
        assert await cur.fetchone() == (0,)
        # Le 404 se conserve : c'est un fait sur la source, « cet id n'existe
        # pas », et il évite de le redemander à chaque passe.
        await cur.execute("select http_status from raw_source")
        assert await cur.fetchone() == (404,)


def test_les_sous_requetes_film_ne_demandent_pas_ce_qui_n_existe_pas() -> None:
    """`aggregate_credits`, `episode_groups` et `content_ratings` sont propres
    aux séries — les demander sur un film, c'est ce que la V1 faisait à
    l'envers depuis 2017 avec `releases` et `lists`."""
    assert "aggregate_credits" not in MOVIE_APPEND
    assert "episode_groups" not in MOVIE_APPEND
    assert "content_ratings" not in MOVIE_APPEND
    assert "release_dates" in MOVIE_APPEND, "le pendant film des classifications par âge"
    assert "release_dates" not in SERIES_APPEND
    assert len(MOVIE_APPEND) <= 20, "TMDB plafonne append_to_response à 20 sous-requêtes"


@respx.mock
async def test_la_fiche_film_demande_les_visuels_de_toutes_langues(
    conn, settings: Settings
) -> None:
    """La leçon du 2026-08-11, reprise telle quelle : `images` et `videos`
    suivent `language`, et les versions françaises sont rares. Sans ces deux
    paramètres, on ne récupère qu'une fraction des bandes-annonces."""
    route = respx.get(url__startswith="https://api.themoviedb.org/3/movie/550").mock(
        httpx.Response(200, json=FILM)
    )
    fetcher = build_fetcher(settings)
    async with fetcher:
        await collect_movie(conn, TmdbClient(fetcher, settings), 550)

    demande = str(route.calls[0].request.url)
    assert "include_image_language=fr%2Cen%2Cnull" in demande
    assert "include_video_language=fr%2Cen%2Cnull" in demande
