"""Les flux RSS de la presse culturelle : parsing et normalisation.

Le module fait UNE chose de plus que `feedparser` : il jette. La frontière
juridique du projet est de ne jamais stocker l'expression éditoriale — les
faits et les liens sont libres, l'article ne l'est pas — et certains éditeurs
expédient l'article entier dans le flux (`content:encoded`). On n'irait le
chercher nulle part : il arriverait tout seul.

D'où la normalisation en LISTE BLANCHE : ce qui n'est pas explicitement gardé
est perdu à l'entrée. `title`, `link`, `guid`, `published`, `tags`, et un
`summary` tronqué à la phrase. Écarter à l'entrée plutôt qu'à l'affichage :
ce qui n'est pas en base ne peut pas fuir — ni par un écran, ni par un export,
ni par un futur consommateur qu'on n'imagine pas encore.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

SOURCE = "rss"

# Au-delà, on ne résume plus, on republie. 500 caractères couvrent un chapô
# entier — c'est ce que l'éditeur met lui-même en vitrine dans son flux.
SUMMARY_MAX_CHARS = 500


def _tronquer_phrase(texte: str, limite: int) -> str:
    """Tronque à la dernière phrase complète avant `limite`.

    À la phrase et pas au caractère : la coupe doit rester lisible, et surtout
    stable — la même entrée re-normalisée doit produire le même texte, donc la
    même empreinte, donc aucune ligne de brut en double.
    """
    if len(texte) <= limite:
        return texte
    coupe = texte.rfind(". ", 0, limite)
    return texte[: coupe + 1] if coupe > 0 else texte[:limite]


def _texte_plat(brut: Any) -> str:
    """Le texte d'un champ feedparser, débarrassé de son balisage.

    Les résumés RSS arrivent souvent en HTML. On ne garde que le texte : le
    balisage est de la mise en forme d'éditeur, et il gonflerait l'empreinte
    sans porter d'information de liaison.
    """
    if not brut:
        return ""
    import re

    sans_balises = re.sub(r"<[^>]+>", " ", str(brut))
    return " ".join(sans_balises.split()).strip()


def _date_iso(entree: Any) -> str | None:
    """La date de publication en ISO, ou rien.

    `published_parsed` d'abord, `updated_parsed` en repli — feedparser les
    donne en UTC. La chaîne brute de l'éditeur n'est pas gardée : dix formats
    pour la même information, et c'est l'empreinte qui paierait la variété.
    """
    for champ in ("published_parsed", "updated_parsed"):
        brut = entree.get(champ)
        if brut:
            try:
                return datetime(*brut[:6], tzinfo=UTC).date().isoformat()
            except (TypeError, ValueError):
                continue
    return None


def normaliser(entree: dict[str, Any]) -> dict[str, Any] | None:
    """Une entrée feedparser → le payload en liste blanche, ou rien.

    Rien n'est copié par défaut. Chaque clé gardée est une décision, et la
    liste se lit en entier ici : titre, lien, guid, date, étiquettes, résumé
    tronqué. `content`, `content:encoded`, les médias joints, les auteurs —
    tout le reste n'existe pas pour nous.

    Sans titre ni lien, l'entrée est inutilisable — ni liaison possible, ni
    rien à montrer — et elle est écartée plutôt que stockée vide.
    """
    titre = _texte_plat(entree.get("title"))
    lien = (entree.get("link") or "").strip()
    if not titre or not lien:
        return None

    return {
        "title": titre,
        "link": lien,
        "guid": (entree.get("id") or "").strip() or lien,
        "published": _date_iso(entree),
        "tags": sorted(
            {t.strip() for tag in entree.get("tags") or [] if (t := (tag.get("term") or ""))}
        ),
        "summary": _tronquer_phrase(_texte_plat(entree.get("summary")), SUMMARY_MAX_CHARS),
    }


def parser_flux(texte: str) -> list[dict[str, Any]]:
    """Le flux entier → les payloads normalisés, dans l'ordre du flux.

    `feedparser` avale RSS 0.9x à 2.0 et Atom sans qu'on ait à choisir, et il
    ne lève pas sur un document malformé — il remplit `bozo`. On journalise et
    on garde ce qui se lit : un flux à moitié cassé qui livre ses items vaut
    mieux qu'un flux rejeté en bloc.
    """
    import feedparser

    lu = feedparser.parse(texte)
    if lu.get("bozo"):
        log.warning("flux mal formé (%s) — on garde ce qui se lit", lu.get("bozo_exception"))
    resultats = []
    for entree in lu.get("entries") or []:
        normalise = normaliser(entree)
        if normalise is not None:
            resultats.append(normalise)
    return resultats
