# Le module admin s'exécute sur DEUX toolchains vendorisées : le CPython de
# ./vendor/python et le Node de ./vendor/node. Ni l'un ni l'autre ne vient du
# système, et rien n'est installé globalement.
#
# Pour Python, le piège est connu (voir sourcing/Makefile) : uv ne lit le
# répertoire de ses interpréteurs que dans UV_PYTHON_INSTALL_DIR — ce n'est pas
# une clé de uv.toml — et sans lui un `uv run` détruit la venv et la recrée sur
# ~/.local/share/uv, silencieusement. Mêmes trois verrous ici : la variable est
# exportée, aucune cible n'appelle `uv run`, et `guard` échoue avant d'exécuter
# quoi que ce soit.
#
# Pour Node, le piège symétrique serait de laisser `npm` résoudre `node` dans le
# PATH du shell. Toutes les cibles préfixent donc le PATH par vendor/node/bin.
export UV_PYTHON_INSTALL_DIR := $(CURDIR)/vendor/python

PY_VERSION   := $(shell cat .python-version)
NODE_VERSION := $(shell cat .node-version)

VENDOR   := $(CURDIR)/vendor
VENV     := $(CURDIR)/.venv
BIN      := $(VENV)/bin
NODE_DIR := $(VENDOR)/node
NODE_BIN := $(NODE_DIR)/bin
FRONT    := $(CURDIR)/../front
WWW      := $(CURDIR)/../www

# Node est publié par plateforme ; on résout la bonne archive plutôt que de la
# figer, pour que le même Makefile serve sur le poste (darwin/arm64) et sur le
# serveur (linux/x64).
UNAME_S := $(shell uname -s)
UNAME_M := $(shell uname -m)
NODE_OS := $(if $(filter Darwin,$(UNAME_S)),darwin,linux)

# `uname -m` ment sous Rosetta : un make lancé en x86_64 sur un Mac Apple
# Silicon répond `x86_64`, et on installerait un Node Intel qui tournerait en
# traduction. Sur macOS on demande donc au noyau plutôt qu'au processus.
NODE_ARCH := $(shell \
  if [ "$(UNAME_S)" = "Darwin" ] && [ "$$(sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ]; then \
    echo arm64; \
  elif [ "$(UNAME_M)" = "arm64" ] || [ "$(UNAME_M)" = "aarch64" ]; then \
    echo arm64; \
  else \
    echo x64; \
  fi)
NODE_PKG  := node-v$(NODE_VERSION)-$(NODE_OS)-$(NODE_ARCH)
NODE_URL  := https://nodejs.org/dist/v$(NODE_VERSION)/$(NODE_PKG).tar.gz
NODE_SUMS := https://nodejs.org/dist/v$(NODE_VERSION)/SHASUMS256.txt

NPM := PATH="$(NODE_BIN):$$PATH" $(NODE_BIN)/npm

# --- Elasticsearch, la troisième toolchain vendorisée ------------------------
#
# Même régime que Node : version figée dans .es-version, archive vérifiée
# contre la somme publiée avant d'être ouverte, rien d'installé dans le
# système. L'archive embarque son JDK — aucun Java à installer. Sur le
# serveur, il vient d'apt (voir doc/recherche-elasticsearch.md) : ce bloc ne
# sert que le poste.
ES_VERSION := $(shell cat .es-version)
ES_DIR     := $(VENDOR)/elasticsearch
# Elastic nomme les architectures autrement que Node : aarch64 et x86_64.
ES_ARCH    := $(if $(filter arm64,$(NODE_ARCH)),aarch64,x86_64)
ES_PKG     := elasticsearch-$(ES_VERSION)-$(NODE_OS)-$(ES_ARCH)
ES_DL      := https://artifacts.elastic.co/downloads/elasticsearch/$(ES_PKG).tar.gz

DB_TEST ?= fivorites_v2_admin_test
PSQL    := psql -h localhost -p 5432 -U postgres -d postgres

.PHONY: bootstrap bootstrap-python bootstrap-node bootstrap-es sync guard doctor test lint fmt \
        db-create migrate serve api web web-build dev es-start es-stop clean

## Installe les trois toolchains et les dépendances.
bootstrap: bootstrap-python bootstrap-node bootstrap-es
	@$(MAKE) --no-print-directory guard
	@$(MAKE) --no-print-directory doctor || true

bootstrap-python:
	uv python install $(PY_VERSION)
	uv sync --all-groups

## CPython et Node dans vendor/, jamais dans le système. L'archive est vérifiée
## contre les sommes publiées par nodejs.org avant d'être ouverte.
bootstrap-node:
	@if [ -x "$(NODE_BIN)/node" ] && [ "v$(NODE_VERSION)" = "$$($(NODE_BIN)/node -v)" ]; then \
	  echo "node $(NODE_VERSION) déjà présent dans vendor/"; \
	else \
	  set -e; \
	  echo "téléchargement de $(NODE_PKG)"; \
	  tmp=$$(mktemp -d); \
	  curl -fsSL "$(NODE_URL)" -o "$$tmp/$(NODE_PKG).tar.gz"; \
	  curl -fsSL "$(NODE_SUMS)" -o "$$tmp/SHASUMS256.txt"; \
	  (cd "$$tmp" && grep " $(NODE_PKG).tar.gz$$" SHASUMS256.txt | shasum -a 256 -c -); \
	  rm -rf "$(NODE_DIR)"; mkdir -p "$(NODE_DIR)"; \
	  tar -xzf "$$tmp/$(NODE_PKG).tar.gz" -C "$(NODE_DIR)" --strip-components=1; \
	  rm -rf "$$tmp"; \
	  echo "node $$($(NODE_BIN)/node -v) installé dans vendor/node"; \
	fi
	cd $(FRONT) && $(NPM) install --no-audit --no-fund

## Elasticsearch dans vendor/, vérifié contre la somme sha512 publiée.
## La configuration est réécrite à chaque passage : c'est elle qui fait de
## l'archive générique un mono-nœud local sans sécurité — la source de vérité
## est ici, pas dans vendor/.
bootstrap-es:
	@if [ -f "$(ES_DIR)/.version" ] && [ "$(ES_VERSION)" = "$$(cat $(ES_DIR)/.version)" ]; then \
	  echo "elasticsearch $(ES_VERSION) déjà présent dans vendor/"; \
	else \
	  set -e; \
	  echo "téléchargement de $(ES_PKG) (~650 Mo)"; \
	  tmp=$$(mktemp -d); \
	  curl -fsSL "$(ES_DL)" -o "$$tmp/$(ES_PKG).tar.gz"; \
	  curl -fsSL "$(ES_DL).sha512" -o "$$tmp/$(ES_PKG).tar.gz.sha512"; \
	  (cd "$$tmp" && shasum -a 512 -c "$(ES_PKG).tar.gz.sha512"); \
	  rm -rf "$(ES_DIR)"; mkdir -p "$(ES_DIR)"; \
	  tar -xzf "$$tmp/$(ES_PKG).tar.gz" -C "$(ES_DIR)" --strip-components=1; \
	  rm -rf "$$tmp"; \
	  echo "$(ES_VERSION)" > "$(ES_DIR)/.version"; \
	  echo "elasticsearch $(ES_VERSION) installé dans vendor/elasticsearch"; \
	fi
	@printf '%s\n' \
	  "# Écrit par \`make bootstrap-es\` — modifier le Makefile, pas ce fichier." \
	  "cluster.name: fivorites" \
	  "node.name: poste" \
	  "discovery.type: single-node" \
	  "# Pas de TLS ni de comptes : le port n'écoute que sur 127.0.0.1, et la" \
	  "# sécurité d'ES 9 exigerait sinon une cérémonie de certificats sans objet." \
	  "xpack.security.enabled: false" \
	  "# Le machine learning d'ES réserve de la mémoire pour rien ici." \
	  "xpack.ml.enabled: false" \
	  "http.host: 127.0.0.1" \
	  "transport.host: 127.0.0.1" \
	  "# Les données restent dans vendor/ : reconstruites par \`search reindex\`," \
	  "# donc jetables avec le reste de la toolchain." \
	  "path.data: $(ES_DIR)/data" \
	  "path.logs: $(ES_DIR)/logs" \
	  "# Les seuils de disque d'ES sont en POURCENTAGE par défaut (85/90/95 %)," \
	  "# et un poste plein à 99 % refuse alors d'allouer le moindre shard — vécu" \
	  "# ici, cluster « red » à vide. En absolu, ES travaille tant qu'il reste de" \
	  "# la place, et s'arrête net avant de remplir le disque." \
	  "cluster.routing.allocation.disk.watermark.low: 10gb" \
	  "cluster.routing.allocation.disk.watermark.high: 6gb" \
	  "cluster.routing.allocation.disk.watermark.flood_stage: 4gb" \
	  > "$(ES_DIR)/config/elasticsearch.yml"
	@mkdir -p "$(ES_DIR)/config/jvm.options.d"
	@printf '%s\n' \
	  "# Écrit par \`make bootstrap-es\`. Un gigaoctet suffit : ~1,5 M de documents" \
	  "# minimaux par univers, et la machine porte aussi Postgres et les" \
	  "# entraînements — ES n'a pas à prendre la moitié de la RAM comme il le" \
	  "# fait par défaut." \
	  "-Xms1g" \
	  "-Xmx1g" \
	  > "$(ES_DIR)/config/jvm.options.d/fivorites.options"

## Met à jour les dépendances Python depuis uv.lock.
sync:
	uv sync --all-groups
	@$(MAKE) --no-print-directory guard

## Échoue si une toolchain a dérivé hors de vendor/. Prérequis de toute cible
## qui exécute du code : la dérive se voit avant, pas après.
guard:
	@test -x $(BIN)/python || { echo "venv absente — lancer \`make bootstrap\`"; exit 1; }
	@base=$$($(BIN)/python -c 'import sys; print(sys.base_prefix)'); \
	case "$$base" in \
	  $(VENDOR)/*) echo "python vendorisé OK — $$base" ;; \
	  *) echo "ERREUR : la venv pointe sur $$base, hors $(VENDOR)"; \
	     echo "         un \`uv run\` lancé sans le Makefile l'a probablement recréée."; \
	     echo "         correction : make bootstrap"; exit 1 ;; \
	esac
	@test -x $(NODE_BIN)/node || { echo "node absent de vendor/ — \`make bootstrap-node\`"; exit 1; }
	@echo "node vendorisé OK — $$($(NODE_BIN)/node -v) dans $(NODE_DIR)"

doctor: guard
	$(BIN)/fiv-admin doctor

migrate: guard
	$(BIN)/fiv-admin db migrate

## Crée la base de test propre à l'administration. Idempotent.
##
## Distincte de `fivorites_v2_test`, où `sourcing` fait tourner la sienne : les
## deux suites tronquent les mêmes tables, et les faire cohabiter revient à les
## faire échouer l'une l'autre dès qu'elles tournent en même temps.
db-create:
	@$(PSQL) -tAc "select 1 from pg_database where datname = '$(DB_TEST)'" | grep -q 1 \
	  && echo "base $(DB_TEST) déjà présente" \
	  || $(PSQL) -c "create database $(DB_TEST) owner fivorites_v2"

test: guard
	$(BIN)/pytest

lint: guard
	$(BIN)/ruff check src tests
	$(BIN)/ruff format --check src tests
	cd $(FRONT) && $(NPM) run lint

fmt: guard
	$(BIN)/ruff format src tests
	$(BIN)/ruff check --fix src tests

# --- Exécution ---------------------------------------------------------------

## L'API seule, avec rechargement à chaud. Sert aussi le front s'il est
## construit (make web-build).
api: guard
	$(BIN)/fiv-admin serve --reload

## Le front seul, servi par Vite sur 5173, qui relaie /api vers l'API.
web: guard
	cd $(FRONT) && $(NPM) run dev

## Les deux, côte à côte. C'est la cible de travail au quotidien.
dev:
	@$(MAKE) --no-print-directory -j2 api web

## Construit le front dans web/dist. À partir de là, `serve` suffit : une seule
## origine, plus de CORS, plus de Vite.
web-build: guard
	cd $(FRONT) && $(NPM) run build

serve: guard
	$(BIN)/fiv-admin serve

## Elasticsearch en arrière-plan. Idempotent : ne relance pas s'il répond déjà.
## L'API s'en passe (repli ILIKE), donc il n'est pas accroché à `dev` : on le
## démarre une fois, il reste là.
es-start:
	@if curl -fsS http://127.0.0.1:9200/ >/dev/null 2>&1; then \
	  echo "elasticsearch répond déjà sur 127.0.0.1:9200"; \
	else \
	  test -x "$(ES_DIR)/bin/elasticsearch" || { echo "absent — \`make bootstrap-es\`"; exit 1; }; \
	  "$(ES_DIR)/bin/elasticsearch" -d -p "$(ES_DIR)/es.pid"; \
	  printf "démarrage"; \
	  for i in $$(seq 1 60); do \
	    curl -fsS http://127.0.0.1:9200/_cluster/health >/dev/null 2>&1 && break; \
	    printf "."; sleep 1; \
	  done; echo; \
	  curl -fsS http://127.0.0.1:9200/ >/dev/null 2>&1 \
	    && echo "elasticsearch prêt — pid $$(cat $(ES_DIR)/es.pid)" \
	    || { echo "ERREUR : pas de réponse — voir $(ES_DIR)/logs/fivorites.log"; exit 1; }; \
	fi

es-stop:
	@test -f "$(ES_DIR)/es.pid" \
	  && { kill "$$(cat $(ES_DIR)/es.pid)" && echo "arrêté"; rm -f "$(ES_DIR)/es.pid"; } \
	  || echo "pas de fichier pid — déjà arrêté ?"

clean:
	rm -rf .venv .pytest_cache .ruff_cache $(FRONT)/node_modules
	find $(WWW) -mindepth 1 ! -name README.md -delete
	find src tests -name __pycache__ -type d -exec rm -rf {} +
