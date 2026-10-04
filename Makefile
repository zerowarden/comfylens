LIBRARY ?=
# Empty PORT and HOST defer to config.toml.
PORT ?=
HOST ?=
WATCH ?= 1
N ?= 100000
SYNTHETIC ?= /tmp/comfylens-synthetic

NPM := npm --prefix frontend
WATCH_FLAG := $(if $(filter 1,$(strip $(WATCH))),--watch)
SERVE_ARGS := $(if $(strip $(PORT)),--port $(PORT)) $(if $(strip $(HOST)),--host $(HOST))
DEV_PORT_ENV := $(if $(strip $(PORT)),COMFYLENS_PORT=$(PORT))
NODE_MODULES := frontend/node_modules/.package-lock.json
WEB := src/comfylens/web/index.html
FRONTEND_SOURCES := $(shell find frontend/src -type f) frontend/index.html \
	frontend/package.json frontend/vite.config.ts $(wildcard frontend/tsconfig*.json)

.DEFAULT_GOAL := run
.PHONY: help run serve dev install build index report test lint check synthetic clean library

library:
	@test -n "$(strip $(LIBRARY))" || { echo "Set LIBRARY, e.g. make LIBRARY=/path/to/comfyui/output" >&2; exit 2; }

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-10s %s\n", $$1, $$2}'
	@echo "  Variables: LIBRARY=$(or $(LIBRARY),unset) PORT=$(or $(PORT),config) HOST=$(or $(HOST),config) WATCH=$(strip $(WATCH))"

run: library build ## Build what is stale, then serve LIBRARY (indexes in the background, opens a browser)
	uv run comfylens serve "$(LIBRARY)" $(SERVE_ARGS) $(WATCH_FLAG)

serve: run ## Alias for run

dev: library $(NODE_MODULES) ## API server and Vite dev server with hot reload; Ctrl-C stops both
	@echo "UI with hot reload: http://localhost:5173/   API: http://$(or $(HOST),127.0.0.1):$(or $(PORT),8765)/"
	@trap 'kill 0' INT TERM EXIT; \
	uv run comfylens serve "$(LIBRARY)" --no-open $(SERVE_ARGS) $(WATCH_FLAG) & \
	$(DEV_PORT_ENV) $(NPM) run dev; \
	wait

install: $(NODE_MODULES) ## Install Python and frontend dependencies
	uv sync

build: $(WEB) ## Build the frontend into src/comfylens/web/ (only when sources changed)

$(NODE_MODULES): frontend/package-lock.json
	$(NPM) ci --no-fund --no-audit

$(WEB): $(NODE_MODULES) $(FRONTEND_SOURCES)
	$(NPM) run build

index: library ## Index LIBRARY without serving it
	uv run comfylens index "$(LIBRARY)"

report: library ## Print the report for LIBRARY
	uv run comfylens report "$(LIBRARY)"

test: $(NODE_MODULES) ## Run the Python and frontend tests
	uv run pytest
	$(NPM) test

lint: $(NODE_MODULES) ## ruff, pyright, ESLint and Prettier
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright
	$(NPM) run lint

check: lint test ## Everything CI would run

synthetic: ## Write N synthetic images to SYNTHETIC
	uv run python scripts/make_synthetic_library.py $(N) "$(SYNTHETIC)"

clean: ## Remove the built frontend and tool caches (never the library, catalog or thumbnails)
	rm -rf src/comfylens/web .pytest_cache .ruff_cache
