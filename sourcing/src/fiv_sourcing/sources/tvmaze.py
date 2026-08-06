"""TVmaze : les dates, les épisodes, le calendrier de diffusion.

Trois entrées, dans l'ordre de fiabilité décroissante — et la troisième n'est
jamais acceptée sur sa seule ressemblance textuelle :

  1. `P8600`, l'identifiant TVmaze porté par Wikidata ;
  2. `lookup?imdb=`, quand on connaît l'`imdb_id` ;
  3. la recherche par titre, **confirmée par égalité d'`imdb_id`**.

La mesure du 2026-08-06 sur 64 paires vérifiées a tranché le protocole de la
troisième voie. Le seuil de score initialement retenu (≥ 0,9) rejetait 23 bons
appariements sur 58 et laissait quand même passer le seul faux positif — deux
séries s'appellent *Teen Wolf*, aucun score textuel ne les départagera jamais.
La réponse de recherche embarque `externals.imdb` gratuitement : l'égalité
confirme 50 cas sur 51 et oppose son veto à l'unique erreur.

D'où la règle : le titre sert à **chercher**, l'`imdb_id` à **décider**. Sans
identifiant des deux côtés, on préfère ne rien écrire — une ligne fausse dans
`riche_source` est plus coûteuse qu'une ligne absente, parce qu'elle ne se
signale pas.
"""

from __future__ import annotations

from typing import Any

from fiv_sourcing.http import FetchResult, HttpFetcher

SOURCE = "tvmaze"
BASE_URL = "https://api.tvmaze.com"


class TvmazeClient:
    def __init__(self, fetcher: HttpFetcher) -> None:
        self._fetcher = fetcher

    async def show(self, show_id: str | int) -> FetchResult:
        """La série et ses épisodes en un appel. `embed` évite de payer une
        seconde requête pour une donnée qui ne vit jamais sans la première."""
        return await self._fetcher.get_json(f"{BASE_URL}/shows/{show_id}", {"embed": "episodes"})

    async def by_imdb(self, imdb_id: str) -> FetchResult:
        return await self._fetcher.get_json(f"{BASE_URL}/lookup/shows", {"imdb": imdb_id})

    async def search(self, titre: str) -> FetchResult:
        return await self._fetcher.get_json(f"{BASE_URL}/search/shows", {"q": titre})


def choisir_par_titre(payload: Any, imdb_id: str | None) -> int | None:
    """Le candidat dont l'`imdb_id` correspond. None si aucun ne le confirme.

    On balaie toute la liste et pas seulement le premier : la mesure a montré
    un cas où le bon candidat était présent mais pas en tête.
    """
    if not imdb_id or not isinstance(payload, list):
        return None
    for candidat in payload:
        show = candidat.get("show") or {}
        if (show.get("externals") or {}).get("imdb") == imdb_id:
            identifiant = show.get("id")
            return int(identifiant) if identifiant is not None else None
    return None


def lire_show(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Les faits qu'on retient, et le texte quand il y en a."""
    if not payload or not payload.get("id"):
        return None

    episodes = ((payload.get("_embedded") or {}).get("episodes")) or []
    diffuseur = payload.get("network") or payload.get("webChannel") or {}
    resumes = [_sans_balises(e.get("summary") or "") for e in episodes]
    resumes = [r for r in resumes if r]

    return {
        "id": payload["id"],
        "url": payload.get("url"),
        "nom": payload.get("name"),
        "statut": payload.get("status"),
        "premiere": payload.get("premiered"),
        "fin": payload.get("ended"),
        "diffuseur": diffuseur.get("name"),
        "pays": ((diffuseur.get("country") or {}).get("code")),
        "calendrier": payload.get("schedule") or {},
        "episodes": len(episodes),
        "episodes_dates": sum(1 for e in episodes if e.get("airdate")),
        "imdb": (payload.get("externals") or {}).get("imdb"),
        # Les résumés d'épisode sont la seule matière textuelle de TVmaze, et
        # elle est rare : une série trouvée sur trois en a. D'où leur
        # concaténation ici plutôt qu'un champ par épisode — c'est un bloc à
        # noter, pas une donnée à interroger.
        "texte": "\n\n".join(resumes) or None,
    }


def images(payload: dict[str, Any] | None) -> list[dict[str, str]]:
    """L'affiche de la série. TVmaze n'expose pas de galerie sur cet endpoint ;
    c'est un visuel de repli, pas une bibliothèque."""
    image = (payload or {}).get("image") or {}
    url = image.get("original") or image.get("medium")
    return [{"type": "poster", "url": url}] if url else []


def _sans_balises(html: str) -> str:
    """TVmaze rend ses résumés en HTML — `<p>` et `<b>`, rien de plus. Un
    parseur complet serait disproportionné ; ce qu'on veut, c'est du texte à
    donner à noter."""
    texte, dans_balise = [], False
    for caractere in html:
        if caractere == "<":
            dans_balise = True
        elif caractere == ">":
            dans_balise = False
        elif not dans_balise:
            texte.append(caractere)
    return (
        "".join(texte)
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&nbsp;", " ")
        .strip()
    )
