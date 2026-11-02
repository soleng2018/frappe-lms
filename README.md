# Nile Workshop LMS

A Frappe LMS that certifies students for a hands on lab. It runs as Docker containers behind an existing Traefik, and students log in through Authentik. Scope: [docs/scope/scope.md](docs/scope/scope.md). Design: [docs/specs/](docs/specs/).

## 1. Prerequisites

You need all of these before you start.

| Need | Why |
|---|---|
| Linux host with Docker Engine and the Compose plugin (`docker compose`), enabled at boot | Runs everything. Containers restart after a reboot only if Docker starts. |
| `make`, `git`, `curl`, `sha256sum` | The Makefile and the build scripts use them. |
| An existing Traefik v3 container on an external Docker network (default name `traefik`) with a `websecure` entrypoint and a `letsencrypt` certificate resolver | Routes HTTPS to the LMS. This repo does not start Traefik. |
| A public DNS name for the LMS (for example `guide.nile.global`) pointing at the host that runs Traefik | It becomes the Frappe site name and the Traefik host rule. It cannot change after the first start. |
| A running Authentik with admin access | Students and admins log in through it. |
| Internet access during the first build | Pulls the base images and clones Frappe, LMS and payments at pinned tags. |
| `uv` and Python 3.12 (only if you run the `tools` code or tests on the host) | Lint and unit tests. Not needed to run the stack. |

## 2. Secrets and settings you need

Everything lives in one file, `.env`, at the repo root. It is never committed and should be mode 0600. `.env.sample` lists every key.

**You must supply these** (no generated value can replace them):

| Key | What it is |
|---|---|
| `LMS_HOSTNAME` | The public hostname of the LMS. Fixed after first start. |
| `AUTHENTIK_HOSTNAME` | The hostname of your Authentik. |
| `AUTHENTIK_API_TOKEN` | An Authentik API token that may create providers, applications and groups. |

**Generated for you** by `make init` the first time (it never overwrites a key that already has a value):

| Key | What it is |
|---|---|
| `LMS_ADMIN_PASSWORD` | Password of the Frappe `Administrator`. |
| `DB_ROOT_PASSWORD` | MariaDB root password. MariaDB ignores a change after the first start. |
| `LMS_ENCRYPTION_KEY` | Frappe `encryption_key`. It encrypts every password field, so a restore is impossible without it. Back it up. |
| `LMS_API_KEY`, `LMS_API_SECRET` | API credentials of the service user that the tools container uses. |

**Defaults you may change:** `LMS_SERVICE_USER`, `AUTHENTIK_APP_SLUG`, `AUTHENTIK_ADMIN_GROUP`, `AUTHENTIK_STUDENT_GROUP_PREFIX`, `AUTHENTIK_STUDENT_GROUP_SUFFIX`, `TRAEFIK_NETWORK`, `TRAEFIK_ENTRYPOINT`, `TRAEFIK_CERT_RESOLVER`.

Version pins are not secrets. They live in the committed `deploy/versions.env`.

## 3. Quick start

```bash
git clone <this repo> && cd <this repo>
make init          # creates .env and fills generated secrets
$EDITOR .env       # set LMS_HOSTNAME, AUTHENTIK_HOSTNAME, AUTHENTIK_API_TOKEN
make up            # fetch upstream, build the image, start the stack
make ps            # every long running service should show (healthy)
make tools CMD=whoami   # proves the API path: prints the service user name
```

The first `make up` builds the image, which takes a while. `configurator` and `create-site` run once and exit 0. Then the long running services become healthy.

## 4. Commands

| Command | Does |
|---|---|
| `make init` | Create `.env` and generate missing secrets. |
| `make build` | Fetch the pinned frappe_docker checkout and build the image. |
| `make up` | Build, then start the stack in the background. |
| `make down` | Stop the stack. Volumes (database, site files) are kept. |
| `make ps` | Show all containers of the stack. |
| `make logs` | Last 100 log lines per service. |
| `make tools CMD=<command>` | Run a tools command in the tools container. Today: `init`, `whoami`. |

Tests, run from `tools/`: `uv run pytest` runs the unit tests. `uv run pytest -m integration` runs the stack tests, which need the stack running and a `.env`. They rerun `create-site` against your live site, which keeps it and changes nothing except pending migrations.

Planned in specs 0002 and 0003 (not built yet): `make hooks`, `make lint`, `make fmt`, `make test`, `make check`.

## 5. Layout

- `deploy/`: compose file, image build, version pins, container scripts.
- `tools/`: Python package for setup scripts.
- `apps/nile_auth/`: custom Frappe app (login rules from Authentik groups).
- `content/`: courses. `brand/`: brand assets (do not edit). `docs/`: scope, specs, reviews.

## 6. Keeping this file current

This README is updated at the end of every work turn that changes how the repo is set up or used. See the rules in [AGENTS.md](AGENTS.md).
