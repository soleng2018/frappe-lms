# Thin wrapper over docker compose. Feature "single config & secrets file" adds the preflight checks.
APPS_HASH = $(shell sha256sum deploy/apps.json | cut -c1-16)
COMPOSE_BASE = APPS_HASH=$(APPS_HASH) REPO_DIR=$(CURDIR) docker compose --project-directory . -f deploy/compose.yaml
COMPOSE      = $(COMPOSE_BASE) --env-file deploy/versions.env --env-file .env
COMPOSE_INIT = $(COMPOSE_BASE) --env-file deploy/versions.env --env-file .env.sample
TOOLS_RUN    = run --rm --no-deps --user "$$(id -u):$$(id -g)" tools

.PHONY: init build up down logs ps tools
init:
	$(COMPOSE_INIT) $(TOOLS_RUN) init
build:
	deploy/fetch-upstream.sh
	$(COMPOSE) build
up: build
	$(COMPOSE) up -d
down:
	$(COMPOSE) down
ps:
	$(COMPOSE) ps -a
logs:
	$(COMPOSE) logs --tail=100
tools:
	$(COMPOSE) $(TOOLS_RUN) $(CMD)
