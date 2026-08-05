# syntax=docker/dockerfile:1.7

# Image du pipeline de sourcing, pour le serveur.
#
# Note sur la vendorisation : `vendor/` n'entre pas dans l'image, et c'est
# voulu — le CPython vendorisé est un binaire macOS/arm64, inutilisable ici. Le
# principe reste le même (un interpréteur figé, jamais celui « du système au
# hasard ») mais l'ancrage change de support : en local c'est vendor/, dans
# l'image c'est le tag de base ci-dessous. Les deux pointent la même version,
# tenue par .python-version.

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.11.0

# uv en étape nommée : c'est la seule forme où `${UV_VERSION}` est interpolé de
# façon fiable — un ARG global ne l'est que dans les instructions FROM.
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# --- construction ------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

COPY --from=uv /uv /usr/local/bin/uv

# uv.toml impose `only-managed`, ce qui a du sens sur le poste local et aucun
# ici : il n'y a pas de Python géré par uv dans l'image, seulement celui de
# l'image de base. Sans cette neutralisation, uv refuserait de l'utiliser et
# tenterait un téléchargement. Les variables d'environnement priment sur
# uv.toml, donc rien à modifier dans le fichier.
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

# Pas de root : le conteneur ne fait que des appels HTTP sortants et des
# écritures en base, il n'a besoin d'aucun privilège.
RUN useradd --system --create-home --uid 10001 fivorites

WORKDIR /app
COPY --from=builder --chown=fivorites:fivorites /app/.venv ./.venv
COPY --chown=fivorites:fivorites src ./src
COPY --chown=fivorites:fivorites migrations ./migrations
COPY --chown=fivorites:fivorites pyproject.toml ./

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MIGRATIONS_DIR=/app/migrations

USER fivorites

# Test de fumée : importe tout le paquet et vérifie que la CLI démarre.
#
# Sans ça, un module oublié dans un commit — le cas classique du `git commit -a`
# qui ignore les fichiers non suivis — produit une image qui se construit sans
# broncher et casse au premier lancement, après déploiement. Ici le build échoue
# tout de suite, sur la machine qui a construit.
RUN python -c "import pkgutil, importlib, fiv_sourcing; \
      [importlib.import_module(m.name) \
       for m in pkgutil.walk_packages(fiv_sourcing.__path__, 'fiv_sourcing.')]" \
    && fiv-sourcing --help > /dev/null

# `doctor` par défaut : lancer l'image sans argument dit si la configuration
# tient debout, plutôt que d'échouer sur une commande métier.
ENTRYPOINT ["fiv-sourcing"]
CMD ["doctor"]
