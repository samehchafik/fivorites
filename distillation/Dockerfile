# syntax=docker/dockerfile:1.7

# Image de distillation. Séparée du reste, et lancée à la demande.
#
# Elle existe parce que le serveur est en Debian 11 : Python 3.9, et rien
# d'installé hors Docker. Plutôt que d'y poser un interpréteur, un uv et une
# pile d'entraînement pour un calcul qui a lieu une fois tous les quelques
# mois, tout tient ici et s'efface avec l'image.
#
# **Torch en version processeur.** La roue par défaut embarque CUDA — deux
# gigaoctets pour du matériel que cette machine n'a pas. L'index séparé descend
# à ~200 Mo.
#
# Le modèle de départ est téléchargé À LA CONSTRUCTION, pas au lancement. Un
# entraînement de vingt heures qui échoue à la première minute parce que le
# réseau tousse serait une perte idiote, et le conteneur n'a de toute façon
# aucune raison d'appeler l'extérieur une fois parti.

ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1

# La borne haute sur transformers n'est pas de la prudence, c'est une
# contrainte mesurée : le code distant de jina v2 fait
# `from transformers.onnx import OnnxConfig` dans son `configuration_bert.py`,
# et ce module a été retiré des versions récentes. Sans la borne, la
# construction échoue sur un ModuleNotFoundError au chargement du modèle.
#
# C'est le prix de `trust_remote_code` : le modèle apporte son implémentation
# d'attention (ALiBi), donc son code, donc les dépendances que ce code suppose
# — figées au jour de sa publication.
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch>=2.4" \
 && pip install --no-cache-dir \
        "transformers>=4.40,<4.49" "einops>=0.8" "onnx>=1.16" "numpy>=1.26,<3" \
        "onnxscript>=0.1"

# Le poids de départ, figé dans l'image. `trust_remote_code` parce que jina v2
# apporte sa propre implémentation d'attention (ALiBi), que transformers ne
# connaît pas.
RUN HF_HUB_OFFLINE=0 python -c "\
from transformers import AutoModel, AutoTokenizer; \
n='jinaai/jina-embeddings-v2-small-en'; \
AutoTokenizer.from_pretrained(n, trust_remote_code=True); \
AutoModel.from_pretrained(n, trust_remote_code=True)"

# Le même uid que l'admin : le répertoire d'échange est déjà à lui, et deux
# comptes différents sur le même volume rendraient la reprise illisible d'un
# conteneur à l'autre.
RUN useradd --system --create-home --uid 10002 fivorites \
 && chown -R fivorites:fivorites /opt/hf

COPY --chown=fivorites:fivorites distiller.py /app/distiller.py

USER fivorites
# Le répertoire de travail est le volume monté : corpus lu, `reprise.pt` écrit,
# élève exporté — tout au même endroit, donc tout survit au conteneur.
WORKDIR /travail

ENTRYPOINT ["python", "/app/distiller.py"]
