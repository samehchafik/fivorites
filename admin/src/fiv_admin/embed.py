"""L'encodeur des dossiers : texte anglais → vecteur, en local.

C'est la réponse à la question ouverte n°5 du plan de notation — « quel
encodeur pour la traîne ? ». Le plan visait un coût nul sur la traîne, ce
qu'un appel d'API par œuvre ne peut pas tenir : à 300 000 séries, ce n'est
pas la facture qui bloque (quelques dizaines d'euros) mais le temps et la
dépendance réseau. Encodées ici, elles passent en moins d'une heure sur le
processeur du serveur, sans sortir de la machine.

`all-MiniLM-L6-v2`, 384 dimensions, servi par ONNX : pas de PyTorch dans
l'image — dix-huit paquets et une centaine de mégaoctets, contre plus d'un
gigaoctet pour la pile d'entraînement complète dont on n'a aucun besoin, ne
faisant qu'inférer.

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

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DIMENSIONS = 384

# L'étiquette rangée en base à côté de chaque vecteur, et dans les poids
# entraînés. C'est elle qui rend le changement d'encodeur sûr : la clé de
# cache et la sélection des poids la comparent, donc un vecteur produit par un
# autre modèle n'est jamais réutilisé par erreur — il est recalculé.
EMBEDDER = "all-MiniLM-L6-v2@384"


@lru_cache(maxsize=1)
def _model(cache_dir: str | None) -> Any:
    """Le modèle, chargé une fois par processus.

    Quatre à cinq secondes au premier appel, une fraction de milliseconde
    ensuite : le charger par œuvre coûterait plus cher que d'encoder.
    """
    from fastembed import TextEmbedding

    return TextEmbedding(MODEL_NAME, cache_dir=cache_dir)


def embed_texts(texts: list[str], *, cache_dir: str | None = None) -> list[list[float]]:
    """Les vecteurs d'une liste de dossiers, dans l'ordre reçu.

    Par lot plutôt qu'un par un : l'inférence ONNX vectorise, et vingt textes
    coûtent à peine plus qu'un seul. C'est ce qui rend l'encodage de la traîne
    tenable — la version par appel d'API imposait une aller-retour réseau par
    œuvre, soit des jours là où il faut désormais moins d'une heure.
    """
    if not texts:
        return []
    return [vector.tolist() for vector in _model(cache_dir).embed(texts)]
