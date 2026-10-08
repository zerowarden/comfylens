LIBRARY ?=
# Empty PORT and HOST defer to config.toml.
PORT ?=
HOST ?=
WATCH ?= 1
N ?= 100000
SYNTHETIC ?= /tmp/comfylens-synthetic
# Host port the container is published on; 80 keeps the URL a bare comfylens.local.
DOCKER_PORT ?= 80

PNPM := pnpm --dir frontend
# With no LIBRARY the CLI and the container read scan.directory from ~/.comfylensrc.
LIBRARY_ARG := $(if $(strip $(LIBRARY)),"$(LIBRARY)")
WATCH_FLAG := $(if $(filter 1,$(strip $(WATCH))),--watch)
HOST_ARG := $(if $(strip $(HOST)),--host $(HOST))
SERVE_ARGS := $(if $(strip $(PORT)),--port $(PORT)) $(HOST_ARG)
NODE_MODULES := frontend/node_modules/.modules.yaml
WEB := src/comfylens/web/index.html
FRONTEND_SOURCES := $(shell find frontend/src -type f) frontend/index.html \
	frontend/package.json frontend/vite.config.ts $(wildcard frontend/tsconfig*.json)

.DEFAULT_GOAL := run
.PHONY: help run serve dev install build index report test lint check synthetic \
	docker docker-build docker-down docker-logs clean

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-14s %s\n", $$1, $$2}'
	@echo "  Variables: LIBRARY=$(or $(LIBRARY),.comfylensrc) PORT=$(or $(PORT),config) HOST=$(or $(HOST),config) WATCH=$(strip $(WATCH)) DOCKER_PORT=$(DOCKER_PORT)"

run: build ## Build what is stale, then serve LIBRARY or the .comfylensrc directory
	uv run comfylens serve $(LIBRARY_ARG) $(SERVE_ARGS) $(WATCH_FLAG)

serve: run ## Alias for run

dev: $(NODE_MODULES) ## API server and Vite dev server with hot reload; Ctrl-C stops both
	@port=$$(uv run comfylens free-port $(SERVE_ARGS)) || exit; \
	trap 'kill 0' INT TERM EXIT; \
	uv run comfylens serve $(LIBRARY_ARG) --no-open --port $$port $(HOST_ARG) $(WATCH_FLAG) & \
	COMFYLENS_PORT=$$port $(PNPM) run dev; \
	wait

install: $(NODE_MODULES) ## Install Python and frontend dependencies
	uv sync

build: $(WEB) ## Build the frontend into src/comfylens/web/ (only when sources changed)

$(NODE_MODULES): frontend/pnpm-lock.yaml
	$(PNPM) install --frozen-lockfile

$(WEB): $(NODE_MODULES) $(FRONTEND_SOURCES)
	$(PNPM) run build

index: ## Index LIBRARY or the .comfylensrc directory without serving it
	uv run comfylens index $(LIBRARY_ARG)

report: ## Print the report for LIBRARY or the .comfylensrc directory
	uv run comfylens report $(LIBRARY_ARG)

test: $(NODE_MODULES) ## Run the Python and frontend tests
	uv run pytest
	$(PNPM) test

lint: $(NODE_MODULES) ## ruff, pyright, ESLint and Prettier
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright
	$(PNPM) run lint

check: lint test ## Everything CI would run

synthetic: ## Write N synthetic images to SYNTHETIC
	uv run python scripts/make_synthetic_library.py $(N) "$(SYNTHETIC)"

docker: ## Build and run the containers; scans LIBRARY or the .comfylensrc directory
	uv run python scripts/docker.py up $(LIBRARY_ARG) --port $(DOCKER_PORT)

docker-build: ## Build the container images without starting them
	uv run python scripts/docker.py build

docker-down: ## Stop the containers (data, cache and configuration are kept)
	uv run python scripts/docker.py down

docker-logs: ## Follow the container logs
	uv run python scripts/docker.py logs

clean: ## Remove the built frontend and tool caches (never the library, catalog or thumbnails)
	rm -rf src/comfylens/web .cache
