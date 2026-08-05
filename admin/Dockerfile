# syntax=docker/dockerfile:1.7

# Image de l'administration, pour le serveur Debian.
#
# **Elle ne contient que l'API.** Le front n'y entre pas : ses sources vivent
# dans `www/` à la racine du dépôt, se construisent dans `www/dist`, et ce
# répertoire est monté en volume par le compose. Trois raisons :
#
#   1. redéployer le front ne demande pas de reconstruire ni de repousser une
#      image — on reconstruit `www/dist` et on recharge la page ;
#   2. l'image reste une image Python, sans Node ni node_modules ;
#   3. le partage des requêtes reste net et vérifiable — `/api/*` au code de
#      cette image, tout le reste au contenu du volume.
#
# Sur la vendorisation : `vendor/` n'entre pas dans l'image, et c'est voulu — le
# CPython vendorisé est un binaire macOS/arm64, inutilisable ici. Le principe ne
# change pas (un interpréteur figé, jamais « celui du système au hasard »), seul
# l'ancrage change de support : en local `vendor/`, dans l'image le tag de base.
# Les deux pointent la même version, tenue par `.python-version`.

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.11.0

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# --- construction ------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

COPY --from=uv /uv /usr/local/bin/uv

# `uv.toml` impose `only-managed`, ce qui a du sens sur le poste local et aucun
# ici : le seul Python disponible est celui de l'image de base. Les variables
# priment sur uv.toml, donc le fichier reste tel quel pour le poste.
ENV UV_PYTHON_PREFERENCE=only-system \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Les dépendances d'abord, le code ensuite : une modification de `src/` ne
# réinstalle pas les paquets.
COPY pyproject.toml uv.lock uv.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- exécution ---------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm

# Pas de root : le service ne fait que servir du HTTP et lire une base.
RUN useradd --system --create-home --uid 10002 fivorites

WORKDIR /app
COPY --from=builder --chown=fivorites:fivorites /app/.venv ./.venv
COPY --chown=fivorites:fivorites src ./src
COPY --chown=fivorites:fivorites migrations ./migrations
COPY --chown=fivorites:fivorites pyproject.toml ./

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MIGRATIONS_DIR=/app/migrations \
    WEB_DIST=/srv/www/dist \
    HOST=0.0.0.0 \
    PORT=8182

USER fivorites

# Test de fumée : importe tout le paquet et vérifie que la CLI démarre.
#
# Sans ça, un module oublié dans un commit produit une image qui se construit
# sans broncher et casse au premier lancement, après déploiement. Ici le build
# échoue tout de suite, sur la machine qui a construit.
RUN python -c "import pkgutil, importlib, fiv_admin; \
      [importlib.import_module(m.name) \
       for m in pkgutil.walk_packages(fiv_admin.__path__, 'fiv_admin.')]" \
    && fiv-admin --help > /dev/null

EXPOSE 8182

ENTRYPOINT ["fiv-admin"]
CMD ["serve"]
