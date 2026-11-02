# Thin wrapper over docker compose. Every target that runs compose first refuses to run if a config
# key is exported in your shell (Compose would let the shell win over .env, the tools would not).
APPS_HASH = $(shell sha256sum deploy/apps.json | cut -c1-16)
COMPOSE_BASE = APPS_HASH=$(APPS_HASH) REPO_DIR=$(CURDIR) docker compose --project-directory . -f deploy/compose.yaml
COMPOSE      = $(COMPOSE_BASE) --env-file deploy/versions.env --env-file .env
# check and init read .env themselves, so they must work when .env is missing or broken.
COMPOSE_INIT = $(COMPOSE_BASE) --env-file deploy/versions.env --env-file .env.sample
TOOLS_RUN    = run --rm --build --quiet-build --no-deps --user "$$(id -u):$$(id -g)" tools

.PHONY: guard init check build up down logs ps tools
guard:
	@bad=""; for k in $$(sed -n 's/^\([A-Z][A-Z0-9_]*\)=.*/\1/p' .env.sample deploy/versions.env); do \
	  if printenv "$$k" >/dev/null; then bad="$$bad $$k"; fi; done; \
	if [ -n "$$bad" ]; then \
	  echo "These config keys are exported in your shell:$$bad" >&2; \
	  echo "Unset them (unset KEY). The file .env is the only place for settings." >&2; exit 1; fi
init: guard
	$(COMPOSE_INIT) $(TOOLS_RUN) init
check: guard
	$(COMPOSE_INIT) $(TOOLS_RUN) config check --for up
build: check
	deploy/fetch-upstream.sh
	$(COMPOSE) build
up: build
	$(COMPOSE) up -d
down: guard
	$(COMPOSE) down
ps: guard
	$(COMPOSE) ps -a
logs: guard
	$(COMPOSE) logs --tail=100
tools: guard
	$(COMPOSE) $(TOOLS_RUN) $(CMD)
