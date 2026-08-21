"""Open Library : le work, ses éditions, ses traductions.

La première référence de l'univers livre (doc/etude-sources-livres.md) : il
n'y a pas de TMDB du livre, et Open Library est ce qui s'en approche — un
modèle work/édition natif, une API libre sans clé ni quota, des dumps
mensuels pour la base de sondage (lot 2).

Trois entrées, dans l'ordre de fiabilité décroissante — le protocole des
séries transposé (« l'identifiant pour décider, le titre pour chercher ») :

  1. `P648`, l'OLID porté par Wikidata — 93 % des grandes œuvres françaises,
     100 % des anglaises ;
  2. la recherche par titre **et auteur** ;
  3. la recherche par titre seul — c'est elle qui rattrape 60 % du corpus
     arabe, dont Wikidata ne porte l'OLID qu'à 23 %.

Contrairement à TVmaze, la troisième voie est acceptée sans confirmation par
identifiant : il n'y en a pas de commun. Le garde-fou est plus faible —
l'auteur quand on l'a, le premier résultat sinon — et c'est mesuré comme
acceptable sur le haut du catalogue, où l'homonymie de titre complet est
rare. Une œuvre mal appariée se voit dans l'admin (la source est affichée) et
se corrige en détachant l'OLID.

Deux pièges connus, tous deux rencontrés pendant l'étude :

  * un work **fusionné** répond `type: /type/redirect` et sa page d'éditions
    répond 404 — on suit `location` une fois ;
  * 13 à 18 % des éditions n'ont **pas de langue taguée** : elles comptent
    dans le total mais dans aucune langue, et la couverture réelle est donc
    un peu meilleure que ce que `langues` affiche.
"""

from __future__ import annotations

from typing import Any

from fiv_sourcing.http import FetchResult, HttpFetcher

SOURCE = "openlibrary"
BASE_URL = "https://openlibrary.org"
COVERS_URL = "https://covers.openlibrary.org/b/id"

# Les couvertures retenues par work. La vignette n'en montre qu'une ; la
# fiche peut en montrer quelques-unes — au-delà, c'est la galerie d'Open
# Library qu'on recopierait.
COUVERTURES_MAX = 4

# Au-delà, l'inventaire est tronqué — Le Petit Prince ou 1984 dépassent. On
# le note dans les faits (`editions.tronque`) plutôt que de paginer : la
# répartition par langue est déjà représentative, et c'est elle qu'on cherche.
EDITIONS_MAX = 500

# MARC 21 → ISO 639-1, pour les langues qu'on affiche et filtre. Un code hors
# de cette table reste tel quel : c'est encore une information (il dit « pas
# une de nos langues cibles »), et l'inventer en ISO serait faux.
_MARC_VERS_ISO = {
    "fre": "fr",
    "eng": "en",
    "spa": "es",
    "ara": "ar",
    "tur": "tr",
    "ger": "de",
    "ita": "it",
    "por": "pt",
    "rus": "ru",
    "jpn": "ja",
    "chi": "zh",
    "kor": "ko",
}


class OpenLibraryClient:
    def __init__(self, fetcher: HttpFetcher) -> None:
        self._fetcher = fetcher

    async def work(self, olid: str) -> FetchResult:
        return await self._fetcher.get_json(f"{BASE_URL}/works/{olid}.json")

    async def book(self, olid: str) -> FetchResult:
        """Une édition (`OL…M`). P648 pointe parfois là plutôt que sur le
        work — constaté au premier crawl réel : l'édition porte son work sous
        `works`, quand elle en a un."""
        return await self._fetcher.get_json(f"{BASE_URL}/books/{olid}.json")

    async def editions(self, olid: str) -> FetchResult:
        return await self._fetcher.get_json(
            f"{BASE_URL}/works/{olid}/editions.json", {"limit": EDITIONS_MAX}
        )

    async def search(self, titre: str, auteur: str | None = None) -> FetchResult:
        """La recherche de work. `fields` restreint la réponse à ce qu'on lit :
        la version complète porte des centaines d'ISBN par document."""
        params: dict[str, Any] = {
            "title": titre,
            "limit": 3,
            "fields": "key,title,edition_count",
        }
        if auteur:
            params["author"] = auteur
        return await self._fetcher.get_json(f"{BASE_URL}/search.json", params)


def work_de_l_edition(payload: dict[str, Any] | None) -> str | None:
    """L'OLID du work d'une édition, None pour une édition orpheline —
    elles existent (constaté : OL19816124M, sans `works`), et une édition
    sans work ne raccorde rien."""
    works = (payload or {}).get("works") or []
    if not works:
        return None
    return (works[0].get("key") or "").rsplit("/", 1)[-1] or None


def redirection(payload: dict[str, Any] | None) -> str | None:
    """L'OLID cible d'un work fusionné, None pour un work normal."""
    if ((payload or {}).get("type") or {}).get("key") != "/type/redirect":
        return None
    cible = (payload or {}).get("location", "").rsplit("/", 1)[-1]
    return cible or None


def lire_work(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """La description et le titre du work. None si la réponse n'en est pas un."""
    if not payload or not payload.get("key"):
        return None
    description = payload.get("description") or ""
    if isinstance(description, dict):
        # Open Library rend tantôt une chaîne, tantôt {type, value}.
        description = description.get("value", "")
    couvertures = [
        int(c)
        for c in payload.get("covers") or []
        # Un id négatif (-1) est le marqueur « couverture retirée » d'OL.
        if isinstance(c, int) and c > 0
    ]
    return {
        "olid": payload["key"].rsplit("/", 1)[-1],
        "titre": payload.get("title"),
        "description": description.strip() or None,
        "couvertures": couvertures[:COUVERTURES_MAX],
    }


def images(work: dict[str, Any]) -> list[dict[str, str]]:
    """Les couvertures du work, au format `riche_source.media` — même forme
    que `tvmaze.images` : des URL servies par la source, jamais recopiées.
    `-L` est la grande taille ; l'affichage réduit lui-même."""
    return [
        {"type": "poster", "url": f"{COVERS_URL}/{c}-L.jpg"} for c in work.get("couvertures") or []
    ]


def lire_editions(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """L'inventaire des éditions : une entrée par langue, pas par édition.

    Un work connu peut porter des centaines d'éditions ; les faits n'ont pas
    à les énumérer. Ce que la couche 1 et l'affichage demandent, c'est « en
    quelles langues, combien, et un ISBN par langue pour le lien d'achat » —
    c'est exactement ce qu'on garde.
    """
    if payload is None:
        return None
    entrees = payload.get("entries")
    if entrees is None:
        return None

    par_langue: dict[str, dict[str, Any]] = {}
    sans_langue = 0
    couvertures: list[int] = []
    for edition in entrees:
        couvertures.extend(
            int(c)
            for c in edition.get("covers") or []
            if isinstance(c, int) and c > 0 and len(couvertures) < COUVERTURES_MAX
        )
        codes = [
            (langue.get("key") or "").rsplit("/", 1)[-1]
            for langue in edition.get("languages") or []
        ]
        codes = [c for c in codes if c]
        if not codes:
            sans_langue += 1
            continue
        isbns = (edition.get("isbn_13") or []) + (edition.get("isbn_10") or [])
        annee = _annee(edition.get("publish_date"))
        for code in codes:
            langue = _MARC_VERS_ISO.get(code, code)
            entree = par_langue.setdefault(langue, {"langue": langue, "nombre": 0})
            entree["nombre"] += 1
            if isbns and "isbn" not in entree:
                entree["isbn"] = isbns[0]
            if annee is not None and annee < entree.get("annee", 10_000):
                entree["annee"] = annee

    total = len(entrees)
    return {
        "editions": sorted(par_langue.values(), key=lambda e: (-e["nombre"], e["langue"])),
        "total": total,
        "sans_langue": sans_langue,
        "tronque": payload.get("size", total) > total,
        # Le repli visuel : beaucoup de works n'ont pas de champ `covers`
        # alors que leurs éditions en portent. Ces ids ne vont PAS dans les
        # facts (ce sont des visuels, pas des faits) — ils nourrissent
        # `images` quand le work est nu.
        "couvertures": couvertures,
    }


def lire_recherche(payload: dict[str, Any] | None) -> str | None:
    """L'OLID du premier **vrai** work trouvé, None sinon.

    La recherche renvoie parfois une clé `/works/OL…M` — une édition
    orpheline montée dans l'index des works (constaté : « Nahj al-Balagha »).
    Un OLID d'édition n'a ni page d'éditions ni description de work : on
    saute au candidat suivant plutôt que d'attacher un identifiant boiteux.
    """
    for doc in (payload or {}).get("docs") or []:
        olid = (doc.get("key") or "").rsplit("/", 1)[-1]
        if olid.endswith("W"):
            return olid
    return None


def _annee(date_publication: str | None) -> int | None:
    """`"June 1995"`, `"1995"`, `"1995-06-01"` → 1995. Open Library ne
    normalise pas ce champ ; on prend le premier bloc de quatre chiffres."""
    if not date_publication:
        return None
    for i in range(len(date_publication) - 3):
        bloc = date_publication[i : i + 4]
        if bloc.isdigit() and 1000 <= int(bloc) <= 2100:
            return int(bloc)
    return None
