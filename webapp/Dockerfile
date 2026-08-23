# syntax=docker/dockerfile:1.7

# Image du site public, pour le serveur Debian.
#
# **Elle ne contient que l'API** — même partage que l'image admin, mêmes
# raisons : le site Astro se construit sur le poste (`make -C site build`),
# le résultat est versionné dans `www-site/` à la racine du dépôt, et c'est ce
# répertoire-là que le compose monte en volume. Redéployer le site, c'est un
# `git pull` ; l'image, elle, reste une image Python sans Node.
#
# Sur la vendorisation : `vendor/` n'entre pas dans l'image — le CPython
# vendorisé est un binaire macOS/arm64. Le principe (un interpréteur figé)
# tient par le tag de base, aligné sur `.python-version`.

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.11.0

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# --- construction ------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

COPY --from=uv /uv /usr/local/bin/uv

# `uv.toml` impose `only-managed` pour le poste ; ici le seul Python est celui
# de l'image de base, et les variables priment sur le fichier.
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
RUN useradd --system --create-home --uid 10003 fivorites

WORKDIR /app
COPY --from=builder --chown=fivorites:fivorites /app/.venv ./.venv
COPY --chown=fivorites:fivorites src ./src
COPY --chown=fivorites:fivorites migrations ./migrations
COPY --chown=fivorites:fivorites pyproject.toml ./

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MIGRATIONS_DIR=/app/migrations \
    WEB_DIST=/srv/www-site \
    HOST=0.0.0.0 \
    PORT=8183

USER fivorites

# Test de fumée : importe tout le paquet et vérifie que la CLI démarre — un
# module oublié casse le build, pas le premier démarrage après déploiement.
RUN python -c "import pkgutil, importlib, fiv_webapp; \
      [importlib.import_module(m.name) \
       for m in pkgutil.walk_packages(fiv_webapp.__path__, 'fiv_webapp.')]" \
    && fiv-webapp --help > /dev/null

EXPOSE 8183

ENTRYPOINT ["fiv-webapp"]
CMD ["serve"]
