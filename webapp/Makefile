# Le module webapp tourne sur le CPython vendorisé de ./vendor/python — même
# régime et mêmes verrous que admin/ et sourcing/ : la variable est exportée,
# aucune cible n'appelle `uv run`, et `guard` échoue avant d'exécuter quoi que
# ce soit si la venv a dérivé hors de vendor/.
#
# Le front public (site/) a son propre Makefile et son propre Node : ce module
# ne connaît que l'API. En production il sert le build versionné de ../www-site
# — voir `web_dist` dans config.py.
export UV_PYTHON_INSTALL_DIR := $(CURDIR)/vendor/python

PY_VERSION := $(shell cat .python-version)

VENDOR := $(CURDIR)/vendor
VENV   := $(CURDIR)/.venv
BIN    := $(VENV)/bin

.PHONY: bootstrap sync guard test lint fmt migrate serve api clean

## Installe la toolchain Python et les dépendances.
bootstrap:
	uv python install $(PY_VERSION)
	uv sync --all-groups
	@$(MAKE) --no-print-directory guard

## Met à jour les dépendances Python depuis uv.lock.
sync:
	uv sync --all-groups
	@$(MAKE) --no-print-directory guard

## Échoue si la toolchain a dérivé hors de vendor/. Prérequis de toute cible
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

test: guard
	$(BIN)/pytest

lint: guard
	$(BIN)/ruff check src tests
	$(BIN)/ruff format --check src tests

fmt: guard
	$(BIN)/ruff format src tests
	$(BIN)/ruff check --fix src tests

migrate: guard
	$(BIN)/fiv-webapp db migrate

## L'API seule, avec rechargement à chaud. Sert aussi le site s'il est
## construit (make -C ../site build).
api: guard
	$(BIN)/fiv-webapp serve --reload

serve: guard
	$(BIN)/fiv-webapp serve

clean:
	rm -rf .venv .pytest_cache .ruff_cache
	find src tests -name __pycache__ -type d -exec rm -rf {} +
