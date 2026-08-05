"""Le service du répertoire statique, et ses en-têtes de cache.

Ces tests gardent une décision qui se retourne contre elle-même si on la fait à
moitié : les fichiers du front portent des **noms fixes**, et c'est
`index.html` qui porte la version, en paramètre de requête. Un mauvais
`Cache-Control` sur l'un des deux, et un déploiement devient invisible pendant
des heures sans qu'aucune erreur n'apparaisse nulle part.

Aucun de ces tests n'ouvre le cycle de vie de l'application : `TestClient` ne le
déclenche qu'en gestionnaire de contexte. C'est voulu — vérifier des en-têtes
HTTP n'a pas à réclamer un Postgres.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from fiv_admin.app import create_app
from fiv_admin.config import Settings

INDEX = """<!doctype html>
<html lang="fr"><head>
<script type="module" src="/assets/index.js?version=1.2.3"></script>
<link rel="stylesheet" href="/assets/style.css?version=1.2.3">
</head><body><div id="root"></div></body></html>
"""


def build_www(root: Path) -> Path:
    """Un répertoire statique tel que `vite build` le produit : trois fichiers,
    aux noms fixes, et la version dans les balises."""
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX, encoding="utf-8")
    (root / "assets" / "index.js").write_text("console.log(1)", encoding="utf-8")
    (root / "assets" / "style.css").write_text("body{}", encoding="utf-8")
    return root


def client_for(web_dist: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                database_url="postgresql://personne@127.0.0.1:1/rien",
                admin_secret_key="secret-de-test",
                cors_origins="",
                web_dist=web_dist,
            )
        )
    )


def test_index_is_revalidated_every_time(tmp_path: Path) -> None:
    """Sans ça, le navigateur garde l'ancien `index.html`, continue de demander
    l'ancienne version des fichiers, et le déploiement reste invisible."""
    response = client_for(build_www(tmp_path / "www")).get("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "?version=1.2.3" in response.text


def test_assets_are_cached_for_a_long_time(tmp_path: Path) -> None:
    """La contrepartie du `?version=` : l'URL change à chaque build, donc rien
    ne périme jamais sous une URL donnée."""
    client = client_for(build_www(tmp_path / "www"))

    for path in ("/assets/index.js", "/assets/style.css"):
        response = client.get(path, params={"version": "1.2.3"})
        assert response.status_code == 200, path
        assert response.headers["cache-control"] == "public, max-age=31536000", path


def test_the_query_string_does_not_take_part_in_routing(tmp_path: Path) -> None:
    """`?version=` n'est qu'une clé de cache : le fichier servi est le même, et
    une version inconnue ne produit pas un 404."""
    client = client_for(build_www(tmp_path / "www"))

    served = client.get("/assets/index.js", params={"version": "9.9.9"})
    naked = client.get("/assets/index.js")

    assert served.status_code == naked.status_code == 200
    assert served.text == naked.text


def test_api_wins_over_the_static_mount(tmp_path: Path) -> None:
    """Le montage couvre `/` : posé avant les routeurs, il avalerait `/api`."""
    assert client_for(build_www(tmp_path / "www")).get("/api/health").json() == {"status": "ok"}


def test_without_a_build_the_page_says_what_is_missing(tmp_path: Path) -> None:
    """Un 404 nu enverrait chercher la panne du mauvais côté."""
    response = client_for(tmp_path / "jamais-construit").get("/")

    assert response.status_code == 503
    assert "www-build" in response.text
