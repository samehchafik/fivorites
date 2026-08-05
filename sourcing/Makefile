# Le projet ne s'exécute QUE sur le CPython de ./vendor.
#
# Deux verrous, parce qu'un seul ne suffit pas :
#
#   1. UV_PYTHON_INSTALL_DIR pointe sur ./vendor/python. uv ne lit ce réglage
#      que dans l'environnement — ce n'est pas une clé de uv.toml — et sans lui
#      il ne reconnaît pas l'interpréteur vendorisé, détruit la venv et la
#      recrée sur ~/.local/share/uv. Silencieusement.
#   2. Aucune cible n'appelle `uv run`. Les outils sont invoqués directement
#      dans .venv/bin, qui est lié au Python de vendor/ : même si uv passait à
#      côté du verrou 1, une exécution de test ou de lint ne pourrait pas
#      basculer sur un autre interpréteur.
#
# `uv` n'apparaît donc que dans bootstrap et sync — les deux seules cibles qui
# ont besoin de résoudre des dépendances — et toujours avec l'export ci-dessus.
export UV_PYTHON_INSTALL_DIR := $(CURDIR)/vendor/python

PY_VERSION := $(shell cat .python-version)
VENDOR     := $(CURDIR)/vendor
VENV       := $(CURDIR)/.venv
BIN        := $(VENV)/bin

DB_NAME  ?= fivorites_v2
DB_OWNER ?= fivorites_v2
DB_HOST  ?= localhost
DB_PORT  ?= 5432
PSQL     := psql -h $(DB_HOST) -p $(DB_PORT) -U postgres -d postgres

.PHONY: bootstrap sync guard doctor test lint fmt db-create db-drop migrate \
        docker-build docker-create docker-migrate docker-doctor docker-down clean

## Installe le CPython vendorisé, la venv et les dépendances.
bootstrap:
	uv python install $(PY_VERSION)
	uv sync --all-groups
	@$(MAKE) --no-print-directory guard
	@$(MAKE) --no-print-directory doctor || true

## Met à jour les dépendances depuis uv.lock.
sync:
	uv sync --all-groups
	@$(MAKE) --no-print-directory guard

## Échoue si la venv n'est plus adossée au Python de vendor/. Prérequis de
## toutes les cibles qui exécutent du code : la dérive est détectée avant, pas
## après avoir fait tourner une suite de tests sur le mauvais interpréteur.
guard:
	@test -x $(BIN)/python || { echo "venv absente — lancer \`make bootstrap\`"; exit 1; }
	@base=$$($(BIN)/python -c 'import sys; print(sys.base_prefix)'); \
	case "$$base" in \
	  $(VENDOR)/*) echo "vendorisation OK — $$base" ;; \
	  *) echo "ERREUR : la venv pointe sur $$base, hors $(VENDOR)"; \
	     echo "         un \`uv run\` lancé sans le Makefile l'a probablement recréée."; \
	     echo "         correction : make bootstrap"; exit 1 ;; \
	esac

## Vérifie l'environnement : interpréteur, base, migrations, schéma, TMDB.
doctor: guard
	$(BIN)/fiv-sourcing doctor

test: guard
	$(BIN)/pytest

lint: guard
	$(BIN)/ruff check src tests
	$(BIN)/ruff format --check src tests

fmt: guard
	$(BIN)/ruff format src tests
	$(BIN)/ruff check --fix src tests

migrate: guard
	$(BIN)/fiv-sourcing db migrate

# --- Postgres local (poste de dev, sans Docker) ------------------------------

## Crée le rôle et la base sur le Postgres déjà installé sur la machine.
## Idempotent.
db-create:
	@$(PSQL) -tAc "select 1 from pg_roles where rolname = '$(DB_OWNER)'" | grep -q 1 \
	  && echo "rôle $(DB_OWNER) déjà présent" \
	  || $(PSQL) -c 'create role $(DB_OWNER) with login'
	@$(PSQL) -tAc "select 1 from pg_database where datname = '$(DB_NAME)'" | grep -q 1 \
	  && echo "base $(DB_NAME) déjà présente" \
	  || $(PSQL) -c 'create database $(DB_NAME) owner $(DB_OWNER)'

## Détruit la base. Ne touche jamais aux autres bases du serveur.
db-drop:
	$(PSQL) -c 'drop database if exists $(DB_NAME)'

# --- Serveur (Docker) --------------------------------------------------------
# Le compose vit à la racine du dépôt : il orchestrera aussi les autres services
# du projet. Ici, des raccourcis pour ne pas avoir à changer de répertoire.

COMPOSE := docker compose -f $(CURDIR)/../docker-compose.yml

docker-build:
	$(COMPOSE) build sourcing

## Crée le conteneur et le réseau sans rien lancer. À faire avant de configurer
## Postgres : c'est ce qui fait apparaître 172.28.0.1 sur l'hôte.
docker-create:
	$(COMPOSE) --profile cli create sourcing

docker-migrate:
	$(COMPOSE) run --rm sourcing db migrate

docker-doctor:
	$(COMPOSE) run --rm sourcing doctor

docker-down:
	$(COMPOSE) down

clean:
	rm -rf .venv .pytest_cache .ruff_cache
	find src tests -name __pycache__ -type d -exec rm -rf {} +
