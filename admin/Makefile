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
WEB      := $(CURDIR)/../www

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

.PHONY: bootstrap bootstrap-python bootstrap-node sync guard doctor test lint fmt \
        migrate serve api web web-build dev clean

## Installe les deux toolchains et les dépendances.
bootstrap: bootstrap-python bootstrap-node
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
	cd $(WEB) && $(NPM) install --no-audit --no-fund

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

test: guard
	$(BIN)/pytest

lint: guard
	$(BIN)/ruff check src tests
	$(BIN)/ruff format --check src tests
	cd $(WEB) && $(NPM) run lint

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
	cd $(WEB) && $(NPM) run dev

## Les deux, côte à côte. C'est la cible de travail au quotidien.
dev:
	@$(MAKE) --no-print-directory -j2 api web

## Construit le front dans web/dist. À partir de là, `serve` suffit : une seule
## origine, plus de CORS, plus de Vite.
web-build: guard
	cd $(WEB) && $(NPM) run build

serve: guard
	$(BIN)/fiv-admin serve

clean:
	rm -rf .venv .pytest_cache .ruff_cache $(WEB)/dist $(WEB)/node_modules
	find src tests -name __pycache__ -type d -exec rm -rf {} +
