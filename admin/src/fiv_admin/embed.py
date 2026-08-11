"""L'encodeur des dossiers : texte anglais → vecteur, en local.

C'est la réponse à la question ouverte n°5 du plan de notation — « quel
encodeur pour la traîne ? ». Le plan visait un coût nul sur la traîne, ce
qu'un appel d'API par œuvre ne peut pas tenir : à 300 000 séries, ce n'est
pas la facture qui bloque (quelques dizaines d'euros) mais le temps et la
dépendance réseau. Encodées ici, elles passent en une dizaine d'heures sur le
processeur du serveur — un traitement par lots qu'on lance et qu'on oublie —
sans jamais sortir de la machine.

`jina-embeddings-v2-small-en`, 512 dimensions, servi par ONNX : pas de
PyTorch dans l'image — dix-huit paquets et 120 Mo, contre plus d'un gigaoctet
pour la pile d'entraînement complète dont on n'a aucun besoin, ne faisant
qu'inférer.

Le choix s'est d'abord porté sur `all-MiniLM-L6-v2`, et c'était une erreur
mesurable : sa fenêtre est de 256 tokens — 128 dans le paquet ONNX servi par
fastembed. Sur un dossier de 5 000 caractères il ne lisait que les 600
premiers, soit le titre, les faits, les genres et une partie des mots-clés.
Tout le reste — synopsis, résumés de saison, échantillon d'épisodes, légendes
visuelles, Wikipédia — n'entrait jamais dans le vecteur. La régression
prédisait donc six axes de goût à partir d'une liste de genres, ce qui
explique qu'elle plafonnait. Celui-ci accepte 8 192 tokens : le dossier entier
tient dedans, avec de la marge.

Le modèle est **figé ici, pas configurable**. Un vecteur n'a de sens qu'au
sein du modèle qui l'a produit : deux encodeurs mélangés dans la même table
donneraient des distances entre des points qui ne vivent pas dans le même
espace. Changer d'encodeur est donc un geste explicite — on change ce nom, et
`EMBEDDER` qui l'accompagne fait que les anciens vecteurs cessent d'être
relus au lieu d'être confondus avec les nouveaux.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

MODEL_NAME = "jinaai/jina-embeddings-v2-small-en"
DIMENSIONS = 512

# L'étiquette rangée en base à côté de chaque vecteur, et dans les poids
# entraînés. C'est elle qui rend le changement d'encodeur sûr : la clé de
# cache et la sélection des poids la comparent, donc un vecteur produit par un
# autre modèle n'est jamais réutilisé par erreur — il est recalculé.
EMBEDDER = "jina-v2-small-en@512"


@lru_cache(maxsize=1)
def _model(cache_dir: str | None, name: str) -> Any:
    """Le modèle, chargé une fois par processus.

    Quatre à cinq secondes au premier appel, une fraction de milliseconde
    ensuite : le charger par œuvre coûterait plus cher que d'encoder.
    """
    from fastembed import TextEmbedding

    return TextEmbedding(name, cache_dir=cache_dir)


# La mémoire de l'attention croît avec le CARRÉ de la longueur, multipliée
# par la taille du lot. Les premiers réglages — 30 000 caractères, lot de 256
# hérité du défaut de fastembed — ont demandé 198 Go sur le serveur : la
# comparaison d'encodeurs est morte au premier lot. Les deux bornes vont donc
# ensemble, et se calculent au lieu de se mesurer :
#
#   mémoire ≈ lot × têtes × tokens² × 4 octets
#   4 × 8 × 3 000² × 4  ≈  1,2 Go   — tenable partout, serveur compris
#
# 12 000 caractères ≈ 3 000 tokens : plus du double du dossier courant
# (~5 000 caractères), donc la troncature ne touche que les fiches hors
# gabarit — celles qui cumulent vingt saisons de résumés.
#
# Ce qu'elle leur coupe dépend entièrement de l'ordre des sections, et c'est ce
# que ce commentaire sous-estimait : elle ne rogne pas la fin d'une section,
# elle en fait disparaître des entières. Docteur House l'a montré — huit
# saisons de résumés consommaient le budget, Wikipédia fermait le dossier et
# n'entrait donc jamais dans le vecteur, alors même que la série était
# enrichie et que le juge, lui, avait lu l'article : 8 en réflexion contre 6,1
# prédits. `dossier.py` place depuis Wikipédia et les légendes AVANT les
# résumés de saisons et d'épisodes, pour que ce qui se fait couper soit la fin
# d'une liste de synopsis répétitifs.
MAX_CHARS = 12_000
LOT = 4


def embed_texts(
    texts: list[str], *, cache_dir: str | None = None, model: str | None = None
) -> list[list[float]]:
    """Les vecteurs d'une liste de dossiers, dans l'ordre reçu.

    `model` n'existe que pour la comparaison d'encodeurs (`training encodeurs`)
    et n'est jamais passé par le chemin de production : celui-ci utilise le
    modèle figé, sans quoi la table mélangerait des espaces vectoriels.

    Par lot plutôt qu'un par un : l'inférence ONNX vectorise, et vingt textes
    coûtent bien moins que vingt fois un seul. C'est ce qui rend l'encodage de
    la traîne tenable — la version par appel d'API imposait un aller-retour
    réseau par œuvre, et la latence dominait tout le reste.
    """
    if not texts:
        return []
    tronques = [text[:MAX_CHARS] for text in texts]
    modele = _model(cache_dir, model or MODEL_NAME)
    return [vector.tolist() for vector in modele.embed(tronques, batch_size=LOT)]


def liberer_modeles() -> None:
    """Vide le cache de modèles — à appeler entre deux candidats d'une comparaison.

    Un seul modèle vit en mémoire à la fois (`maxsize=1`), mais l'éviction du
    précédent n'a lieu qu'au chargement du suivant : sans libération explicite,
    une comparaison de quatre encodeurs finit avec le dernier modèle ET les
    arènes ONNX des précédents — ces arènes gardent leurs pics d'allocation et
    ne rendent jamais rien. Vu en production : douze gigaoctets résidents pour
    une comparaison, sur une machine qui en partage cent vingt.
    """
    _model.cache_clear()
