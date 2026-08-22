"""Le canal RSS : la liste blanche, puis le cycle de collecte.

Les deux contrats qui comptent : rien ne traverse la normalisation sans être
explicitement gardé (frontière juridique), et un passage sur un flux inchangé
ne coûte qu'un 304 (contrat d'agrégateur).
"""

from __future__ import annotations

import httpx
import respx

from fiv_sourcing.actualite import balayer_flux
from fiv_sourcing.enrich import build_fetcher
from fiv_sourcing.sources import rss

# ------------------------------------------------------------ liste blanche

ENTREE = {
    "title": "  <b>Une saison 3</b> pour la série ",
    "link": "https://exemple.fr/article",
    "id": "guid-42",
    "published_parsed": (2026, 8, 20, 10, 0, 0, 0, 0, 0),
    "tags": [{"term": "séries"}, {"term": "netflix"}, {"term": ""}],
    "summary": "<p>Premier point.</p> <p>Second point, plus long. Troisième.</p>",
    # Ce que certains éditeurs expédient et qu'on ne doit JAMAIS stocker :
    "content": [{"value": "L'ARTICLE ENTIER, sous droit d'auteur."}],
    "author": "Prénom Nom",
    "media_thumbnail": [{"url": "https://exemple.fr/img.jpg"}],
}


def test_la_normalisation_est_une_liste_blanche():
    """Chaque clé gardée est une décision ; tout le reste n'existe pas.

    Le test énumère les clés EXACTES du payload : une clé de plus qui
    apparaîtrait — un futur feedparser plus bavard, un copier-coller — ferait
    échouer ici, avant d'atteindre la base.
    """
    payload = rss.normaliser(dict(ENTREE))
    assert payload is not None
    assert set(payload) == {"title", "link", "guid", "published", "tags", "summary"}
    assert payload["title"] == "Une saison 3 pour la série"
    assert payload["guid"] == "guid-42"
    assert payload["published"] == "2026-08-20"
    assert payload["tags"] == ["netflix", "séries"]
    assert "ARTICLE" not in str(payload), "le contenu d'article ne doit jamais traverser"
    assert "Nom" not in str(payload)


def test_le_resume_se_tronque_a_la_phrase():
    long = {"title": "T", "link": "https://x.fr/a", "summary": "Aaa. " * 200}
    payload = rss.normaliser(long)
    assert payload is not None
    assert len(payload["summary"]) <= rss.SUMMARY_MAX_CHARS
    assert payload["summary"].endswith("."), "la coupe tombe sur une phrase complète"


def test_une_entree_sans_titre_ou_sans_lien_est_ecartee():
    assert rss.normaliser({"title": "", "link": "https://x.fr"}) is None
    assert rss.normaliser({"title": "T", "link": ""}) is None


def test_le_guid_retombe_sur_le_lien():
    payload = rss.normaliser({"title": "T", "link": "https://x.fr/a"})
    assert payload is not None
    assert payload["guid"] == "https://x.fr/a"


FLUX = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Test</title>
<item><title>Annonce A</title><link>https://ed.fr/a</link><guid>a</guid>
  <description>Chapô A.</description></item>
<item><title>Annonce B</title><link>https://ed.fr/b</link><guid>b</guid>
  <description>Chapô B.</description></item>
</channel></rss>"""


def test_parser_flux_rend_les_items_dans_l_ordre():
    items = rss.parser_flux(FLUX)
    assert [i["title"] for i in items] == ["Annonce A", "Annonce B"]


# ----------------------------------------------------------------- le sweep


async def _flux_en_base(conn, url: str, editeur: str = "test") -> int:
    async with conn.cursor() as cur:
        await cur.execute(
            "insert into rss_feed (url, editeur) values (%s, %s) returning id",
            (url, editeur),
        )
        return (await cur.fetchone())[0]


@respx.mock
async def test_le_sweep_collecte_puis_honore_le_304(conn, settings):
    """Le cycle complet d'un agrégateur correct : 200 avec validateurs, puis
    If-None-Match au passage suivant, et 304 sans une ligne écrite."""
    feed_id = await _flux_en_base(conn, "https://ed.fr/rss")
    requetes: list[httpx.Request] = []

    def repondre(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        if request.headers.get("If-None-Match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, text=FLUX, headers={"ETag": '"v1"'})

    respx.get("https://ed.fr/rss").mock(side_effect=repondre)

    fetcher = build_fetcher(settings)
    async with fetcher:
        premier = await balayer_flux(conn, fetcher)
        second = await balayer_flux(conn, fetcher)

    assert premier.items_nouveaux == 2
    assert second.inchanges == 1
    assert second.items_vus == 0, "un 304 ne parse rien"
    assert requetes[1].headers.get("If-None-Match") == '"v1"', (
        "le validateur du premier passage doit repartir avec le second"
    )
    async with conn.cursor() as cur:
        await cur.execute("select count(*) from raw_rss_item where feed_id = %s", (feed_id,))
        assert (await cur.fetchone())[0] == 2


@respx.mock
async def test_un_item_reemis_identique_n_ecrit_rien(conn, settings):
    """Les flux ré-émettent leurs vingt derniers items à chaque réponse : sans
    la dédup par empreinte, chaque 200 multiplierait le brut par vingt."""
    await _flux_en_base(conn, "https://ed.fr/rss")
    # Pas d'ETag : le serveur répond 200 à chaque fois, même contenu.
    respx.get("https://ed.fr/rss").mock(httpx.Response(200, text=FLUX))

    fetcher = build_fetcher(settings)
    async with fetcher:
        premier = await balayer_flux(conn, fetcher)
        second = await balayer_flux(conn, fetcher)

    assert premier.items_nouveaux == 2
    assert second.items_vus == 2
    assert second.items_nouveaux == 0, "même contenu, même empreinte, zéro ligne"


@respx.mock
async def test_un_flux_en_erreur_ne_bloque_pas_les_autres(conn, settings):
    """Un éditeur qui tombe un samedi ne doit pas éteindre la collecte du
    week-end : l'erreur se note sur SA ligne, la passe continue."""
    casse = await _flux_en_base(conn, "https://mort.fr/rss", "mort")
    vivant = await _flux_en_base(conn, "https://ed.fr/rss", "vivant")
    respx.get("https://mort.fr/rss").mock(httpx.Response(500))
    respx.get("https://ed.fr/rss").mock(httpx.Response(200, text=FLUX))

    fetcher = build_fetcher(settings)
    async with fetcher:
        report = await balayer_flux(conn, fetcher)

    assert report.erreurs == 1
    assert report.items_nouveaux == 2, "le flux vivant a été collecté malgré le mort"
    async with conn.cursor() as cur:
        await cur.execute("select last_error from rss_feed where id = %s", (casse,))
        assert (await cur.fetchone())[0] == "HTTP 500"
        await cur.execute("select last_error from rss_feed where id = %s", (vivant,))
        assert (await cur.fetchone())[0] is None
