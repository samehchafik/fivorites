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
def _model(cache_dir: str | None) -> Any:
    """Le modèle, chargé une fois par processus.

    Quatre à cinq secondes au premier appel, une fraction de milliseconde
    ensuite : le charger par œuvre coûterait plus cher que d'encoder.
    """
    from fastembed import TextEmbedding

    return TextEmbedding(MODEL_NAME, cache_dir=cache_dir)


# 8 192 tokens ≈ 30 000 caractères de texte anglais. Le plafond est posé bien
# au-dessus des dossiers courants (~5 000) et sert de garde-fou aux fiches
# hors gabarit — une série de vingt-deux saisons cumule des résumés sans
# limite. Tronquer là est sans conséquence : on coupe la fin de la dernière
# section, pas une section entière.
MAX_CHARS = 30_000


def embed_texts(texts: list[str], *, cache_dir: str | None = None) -> list[list[float]]:
    """Les vecteurs d'une liste de dossiers, dans l'ordre reçu.

    Par lot plutôt qu'un par un : l'inférence ONNX vectorise, et vingt textes
    coûtent bien moins que vingt fois un seul. C'est ce qui rend l'encodage de
    la traîne tenable — la version par appel d'API imposait un aller-retour
    réseau par œuvre, et la latence dominait tout le reste.
    """
    if not texts:
        return []
    tronques = [text[:MAX_CHARS] for text in texts]
    return [vector.tolist() for vector in _model(cache_dir).embed(tronques)]
