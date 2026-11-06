# Thin wrapper over docker compose. Every target that runs compose first refuses to run if a config
# key is exported in your shell (Compose would let the shell win over .env, the tools would not).
APPS_HASH = $(shell sha256sum deploy/apps.json | cut -c1-16)
COMPOSE_BASE = APPS_HASH=$(APPS_HASH) REPO_DIR=$(CURDIR) docker compose --project-directory . -f deploy/compose.yaml
COMPOSE      = $(COMPOSE_BASE) --env-file deploy/versions.env --env-file .env
# check and init read .env themselves, so they must work when .env is missing or broken.
COMPOSE_INIT = $(COMPOSE_BASE) --env-file deploy/versions.env --env-file .env.sample
TOOLS_RUN    = run --rm --build --quiet-build --no-deps --user "$$(id -u):$$(id -g)" tools

.PHONY: guard init check build up down logs ps tools verify-branding restart-test hooks lint fmt test compose-config secrets
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

# Spec 0012: the branding checks. The tools container has no docker access, so Inter is checked here.
verify-branding: guard
	$(COMPOSE) exec -T backend fc-match -f 'Inter installed: %{family}\n' Inter | grep -x 'Inter installed: Inter'
	$(COMPOSE) $(TOOLS_RUN) verify branding

# Proves restart and crash recovery (spec 0007). Needs the Docker CLI and sudo on the host.
restart-test: guard
	SERVICES="$$($(COMPOSE) $(TOOLS_RUN) verify services)" deploy/scripts/restart-test.sh

# Code quality (spec 0003). `check` above means the config file, not code.
GITLEAKS_IMAGE = ghcr.io/gitleaks/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f
hooks:
	uv run --frozen --project tools pre-commit install
lint: secrets
	uv run --frozen --project tools pre-commit run --all-files
fmt: lint
secrets:
	docker run --rm -v "$(CURDIR):/repo:ro" $(GITLEAKS_IMAGE) dir /repo --config /repo/.gitleaks.toml --no-banner --redact
compose-config: guard
	APPS_HASH=$(APPS_HASH) REPO_DIR=$(CURDIR) docker compose --project-directory . -f deploy/compose.yaml --env-file deploy/versions.env --env-file .env.sample --profile tools config -q
test:
	uv run --frozen --directory tools pytest --cov --cov-report=term-missing
