"""Wikipédia : l'article, en entier.

`explaintext` sans `exintro` — c'est-à-dire le texte complet, pas le résumé
d'introduction. C'est la différence entre 400 caractères de chapeau et les
5 000 à 30 000 caractères d'intrigue détaillée qui font la matière de notation.

Une requête par langue et par série. Les titres viennent des sitelinks de
Wikidata : chercher par titre dans chaque Wikipédia coûterait une requête de
plus et se tromperait sur les homonymes.
"""

from __future__ import annotations

from typing import Any

from fiv_sourcing.http import FetchResult, HttpFetcher

SOURCE = "wikipedia"


class WikipediaClient:
    def __init__(self, fetcher: HttpFetcher) -> None:
        self._fetcher = fetcher

    async def article(self, lang: str, titre: str) -> FetchResult:
        return await self._fetcher.get_json(
            f"https://{lang}.wikipedia.org/w/api.php",
            {
                "action": "query",
                "prop": "extracts",
                "explaintext": "1",
                # Un sitelink peut pointer une redirection ; sans ceci la
                # réponse serait une page vide plutôt que l'article.
                "redirects": "1",
                "titles": titre,
                "format": "json",
                "formatversion": "2",
            },
        )


def lire_article(payload: dict[str, Any] | None) -> tuple[str, str] | None:
    """(titre canonique, texte). None si la page n'existe pas.

    `formatversion=2` donne une liste de pages plutôt qu'un dictionnaire indexé
    par un identifiant qu'on ne connaît pas à l'avance.
    """
    pages = ((payload or {}).get("query") or {}).get("pages") or []
    for page in pages:
        if page.get("missing"):
            continue
        texte = (page.get("extract") or "").strip()
        if texte:
            return page.get("title", ""), texte
    return None
