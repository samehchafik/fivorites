# Le site public tourne sur le Node vendorisé de ./vendor/node — même régime
# que front/ (voir admin/Makefile) : rien du système, rien de global, et
# toutes les cibles préfixent le PATH par vendor/node/bin pour que npm ne
# résolve jamais un autre node.
#
# Le build sort dans ../www-site, qui est VERSIONNÉ : sur le serveur, le site
# arrive par `git pull` et c'est le service webapp qui le sert — pas de Node
# en production.

NODE_VERSION := $(shell cat .node-version)

VENDOR   := $(CURDIR)/vendor
NODE_DIR := $(VENDOR)/node
NODE_BIN := $(NODE_DIR)/bin

# Node est publié par plateforme ; on résout la bonne archive plutôt que de la
# figer, pour que le même Makefile serve sur le poste (darwin/arm64) et
# ailleurs. `uname -m` ment sous Rosetta : sur macOS on demande au noyau.
UNAME_S := $(shell uname -s)
UNAME_M := $(shell uname -m)
NODE_OS := $(if $(filter Darwin,$(UNAME_S)),darwin,linux)
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

.PHONY: bootstrap guard dev build lint clean

## Node dans vendor/, jamais dans le système. L'archive est vérifiée contre
## les sommes publiées par nodejs.org avant d'être ouverte.
bootstrap:
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
	$(NPM) install --no-audit --no-fund

guard:
	@test -x $(NODE_BIN)/node || { echo "node absent de vendor/ — \`make bootstrap\`"; exit 1; }
	@echo "node vendorisé OK — $$($(NODE_BIN)/node -v) dans $(NODE_DIR)"

## Le site en dev sur 4321, l'API relayée vers 8183 (voir astro.config.mjs).
## Lancer le service à côté : make -C ../webapp api
dev: guard
	$(NPM) run dev

## Construit le site dans ../www-site — le build versionné que webapp sert.
build: guard
	$(NPM) run build

lint: guard
	$(NPM) run lint

clean:
	rm -rf node_modules .astro
