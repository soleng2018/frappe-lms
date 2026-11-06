# Nile Workshop LMS

A Frappe LMS that certifies students for a hands on lab. Everything is set up by script and runs as Docker containers behind the existing Traefik. Scope: [docs/scope/scope.md](docs/scope/scope.md). Brief: [requirements.md](requirements.md).

## Stack

Source of truth: [docs/specs/0001-stack-and-architecture/index.md](docs/specs/0001-stack-and-architecture/index.md).

- **Language / Runtime**: Python. `tools/` on Python 3.12. `apps/nile_auth/` on the Python of the Frappe image.
- **Framework**: Frappe `version-16` (pinned to a release tag) with LMS (pinned tag), plus one custom Frappe app `nile_auth`.
- **Key dependencies**: frappe_docker layered image, MariaDB, redis, nginx `frontend`, Traefik v3.5.0 (existing), Authentik (OIDC), `httpx`, `PyYAML`.
- **Package manager**: `uv` (Python tools). Docker Compose runs everything: one `deploy/compose.yaml`, one dotenv config file.
- **Layout**: `deploy/`, `tools/`, `apps/nile_auth/`, `content/`, `brand/`, `docs/`.

## Build approach

**Tracer Bullet**: prove the whole pipe works with one real thin path, then thicken one strand at a time.

## Commands

Defined by specs 0002 and 0003, built by the scaffold. They do not all exist yet.

```bash
make hooks     # install the pre-commit hook (once per clone)
make lint      # run every hook on all files, then gitleaks on the tree
make fmt       # same as lint (hooks fix what they can; re-run after a fix)
make test      # pytest with coverage, unit tests only
make init      # create .env from the sample
make check     # check the config file (not code)
make up        # check, build, start the stack
make tools CMD=<command>   # run a tools command in the tools container
make verify-branding       # prove the Nile branding on the live site
```

## Specs

Stored in `docs/specs/`. Format: `docs/specs/NNNN-title.md`.

## Rules

- Style: `tools/` uses spaces, 100 columns, Ruff and mypy (standard mode, every signature typed). `apps/nile_auth/` follows Frappe style: tabs, 110 columns, no mypy.
- Never edit or reformat `brand/`, `.claude/`, `.agents/`, `skills-lock.json`, or `uv.lock`.
- Functional style in `tools/`: pure functions by default, immutable data, side effects (HTTP, files, subprocess) pushed to the edges and kept explicit. Avoid classes where a function works. No module level mutable state.
- Expected failures return explicit results or raise one consistent error type with a clear message (name the URL or config key). Never print a secret value.
- Validate config at startup and fail fast, naming every bad key at once.
- Give each module a clear public surface (`__all__` or a deliberate set of public names). Document public functions with a one line Google style docstring.
- No secret in compose, the image, or git. All settings and secrets live in the one dotenv file. Scripts only touch items they created.
- Unit tests must not touch the network or a real `.env`. Integration tests carry the `integration` marker.
- README: `README.md` must start with prerequisites and the secrets needed, then the steps to use the repo. At the end of every turn that changes setup, commands, keys in `.env.sample`, or prerequisites, update `README.md` in the same turn.
- Commits: a plain imperative sentence, short first line, optional body.

## Git

- integration: on
- branch prefix: feat/
- commit: per-milestone

## Agent skills

- [frappe-app-dev](.claude/skills/frappe-app-dev/): `frappe/skills`, Frappe app, DocType, hook, and API conventions
- [docker-compose-patterns](.claude/skills/docker-compose-patterns/): `docker/skills`, compose files, healthchecks, ordering, volumes
- [uv](.claude/skills/uv/): `astral-sh/claude-code-plugins`, Python projects and lock files

Declined: Authentik community MCP server, frappe-manager skill
MCP servers: Frappe built in endpoint (recommended, once the site is up), MariaDB/mcp (recommended, read only, dev only)

## Context files

- [deploy/AGENTS.md](deploy/AGENTS.md) (compose, image build, version pins, container scripts)
- [tools/AGENTS.md](tools/AGENTS.md) (the `nile_tools` package, config key list, how it runs in a container)

<!-- Nested AGENTS.md files are listed here as they are created -->

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
