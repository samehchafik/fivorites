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

Le modèle **se règle** (`EMBEDDER` dans le `.env`), et trois formes cohabitent :
un nom fastembed, `openai/…` pour un encodeur d'API, `local:/chemin` pour un
modèle maison servi en ONNX — c'est par là que revient l'élève distillé.

Ce qui reste vrai, et qui plaidait pour une constante : un vecteur n'a de sens
qu'au sein du modèle qui l'a produit. Mais l'argument demande une **étiquette
rigoureuse**, pas une constante. `etiquette()` la calcule, elle fait partie de
la clé du cache et l'entraînement filtre dessus : deux espaces vectoriels ne
peuvent pas se mélanger, les anciens vecteurs cessent simplement d'être relus.

Ce qui a rendu le réglage nécessaire : mesuré sur 502 œuvres, à dimension
égale, jina rend 1,020 de MAE et `text-embedding-3-large@512` rend 0,853.
L'écart ne vient pas du nombre de dimensions mais de ce que le modèle sait —
jina lit « Lucifer » sans savoir ce que le mot désigne.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

MODEL_NAME = "jinaai/jina-embeddings-v2-small-en"
DIMENSIONS = 512

# L'étiquette rangée en base à côté de chaque vecteur, et dans les poids
# entraînés. C'est elle qui rend le changement d'encodeur sûr : la clé de
# cache et la sélection des poids la comparent, donc un vecteur produit par un
# autre modèle n'est jamais réutilisé par erreur — il est recalculé.
EMBEDDER = "jina-v2-small-en@512"

# Le préfixe d'un modèle servi depuis un dossier local : `local:/opt/models/x`.
# C'est par là que revient l'élève distillé — un `model.onnx` et son tokenizer,
# produits par le projet `distillation/`, avec le pooling et la normalisation
# inclus dans le graphe pour qu'aucune divergence d'implémentation ne s'installe
# entre l'entraînement et la production.
PREFIXE_LOCAL = "local:"

# L'encodeur de secours quand celui de production est une API qui ne répond
# pas. C'est le modèle local, et c'est le seul qui puisse tenir ce rôle : il ne
# dépend de rien.
SECOURS = MODEL_NAME


def etiquette(spec: str) -> str:
    """L'étiquette de rangement d'un encodeur — ce que porte `embedding.embedder`.

    Deux formes cohabitent depuis que la production peut appeler une API :
    `openai/text-embedding-3-large@512` se range sous
    `text-embedding-3-large@512`, un modèle local sous son nom court.

    C'est cette étiquette qui empêche le mélange, et le mélange serait
    silencieux : deux espaces vectoriels dans une même régression ne lèvent
    aucune erreur, ils rendent des poids qui ne veulent rien dire. Elle fait
    partie de la clé du cache, et l'entraînement filtre dessus.
    """
    if spec.startswith("openai/"):
        return spec.removeprefix("openai/")
    if spec.startswith(PREFIXE_LOCAL):
        # Le nom du dossier, pas son chemin : l'élève distillé vit à des
        # emplacements différents selon la machine, et une étiquette qui
        # porterait le chemin ferait recalculer tous les vecteurs au premier
        # déménagement.
        return Path(spec.removeprefix(PREFIXE_LOCAL)).name
    return EMBEDDER if spec == MODEL_NAME else spec


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

# La borne en tokens par défaut du chemin local, quand le modèle ne dit pas la
# sienne. Un élève distillé, lui, la porte dans son `fivorites.json` : le
# graphe ONNX fige le biais ALiBi à la longueur d'export, donc lui donner plus
# de tokens qu'il n'en connaît est une erreur — et une erreur **muette**, le
# modèle rendant un vecteur sur un texte silencieusement tronqué.
MAX_TOKENS = 1024


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
    spec = model or MODEL_NAME
    if spec.startswith(PREFIXE_LOCAL):
        return _encoder_local(spec.removeprefix(PREFIXE_LOCAL), tronques)
    modele = _model(cache_dir, spec)
    return [vector.tolist() for vector in modele.embed(tronques, batch_size=LOT)]


@lru_cache(maxsize=2)
def _session_locale(dossier: str) -> Any:
    """La session ONNX et le tokenizer d'un modèle servi depuis un dossier.

    `onnxruntime` et `tokenizers` sont déjà là — fastembed en dépend — donc
    servir un modèle maison n'ajoute aucune dépendance. Ce qui est ajouté,
    c'est la responsabilité de tokeniser comme à l'entraînement ; d'où le
    tokenizer sauvé à côté du graphe par le script de distillation, plutôt
    qu'un tokenizer reconstruit de mémoire.
    """
    import onnxruntime
    from tokenizers import Tokenizer

    chemin = Path(dossier)
    graphe = chemin / "model.onnx"
    if not graphe.exists():
        raise FileNotFoundError(
            f"{graphe} introuvable — le dossier doit contenir model.onnx et tokenizer.json,"
            " tels que distillation/distiller.py les écrit."
        )
    # La borne vient du modèle quand il la donne. La deviner serait le genre
    # d'erreur qui ne se voit pas : le graphe accepterait la séquence trop
    # longue ou la tronquerait, et rendrait un vecteur plausible sur un texte
    # amputé.
    marque = chemin / "fivorites.json"
    bornes = json.loads(marque.read_text(encoding="utf-8")) if marque.exists() else {}
    tokenizer = Tokenizer.from_file(str(chemin / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=int(bornes.get("maxTokens", MAX_TOKENS)))
    tokenizer.enable_padding()
    return onnxruntime.InferenceSession(str(graphe)), tokenizer


def _encoder_local(dossier: str, textes: list[str]) -> list[list[float]]:
    """Encode avec un modèle maison. Le graphe rend déjà le vecteur normalisé."""
    import numpy as np

    session, tokenizer = _session_locale(dossier)
    vecteurs: list[list[float]] = []
    for depart in range(0, len(textes), LOT):
        lot = textes[depart : depart + LOT]
        encodes = tokenizer.encode_batch(lot)
        ids = np.array([e.ids for e in encodes], dtype=np.int64)
        masque = np.array([e.attention_mask for e in encodes], dtype=np.int64)
        sortie = session.run(None, {"input_ids": ids, "attention_mask": masque})[0]
        vecteurs.extend(v.tolist() for v in sortie)
    return vecteurs


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
    _session_locale.cache_clear()
