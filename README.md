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

Everything lives in one file, `.env`, at the repo root. It is never committed and must be mode 0600, owned by you. `.env.sample` lists every key. It is generated from the key list in `tools/src/nile_tools/config.py`, so edit the list, not the sample (`make` and the tests tell you when they differ).

**Rules for a value:** only letters, digits and `_ . : / @ + = , -`. No quotes, spaces, `$`, `#` or backslash, because Docker Compose and the Python tools read these differently. A pasted token with other characters is rejected with its line number. Do not export these keys in your shell: the Makefile refuses to run if you do.

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

**Fixed after the first start** (never edit once the stack has run): `LMS_HOSTNAME`, `LMS_ADMIN_PASSWORD`, `LMS_ENCRYPTION_KEY`, `LMS_SERVICE_USER`, `LMS_API_KEY`, `LMS_API_SECRET`, `DB_ROOT_PASSWORD`, `AUTHENTIK_APP_SLUG`. **Keep a private copy of `.env`**: if you lose it, the data in the volumes cannot be recovered, and `create-site` refuses to start with a different encryption key.

Version pins are not secrets. They live in the committed `deploy/versions.env`.

## 3. Quick start

```bash
git clone <this repo> && cd <this repo>
make init          # creates .env and fills generated secrets
$EDITOR .env       # set LMS_HOSTNAME, AUTHENTIK_HOSTNAME, AUTHENTIK_API_TOKEN
make check         # lists every bad or missing key at once (make up runs it for you)
make up            # check, fetch upstream, build the image, start the stack
make ps            # every long running service should show (healthy)
make tools CMD=whoami   # proves the API path: prints the service user name
```

The first `make up` builds the image, which takes a while. `configurator` and `create-site` run once and exit 0. Then the long running services become healthy.

## 4. Commands

| Command | Does |
|---|---|
| `make init` | Create `.env` from the sample at mode 0600 and generate missing secrets. Run again after an update: it adds new keys and never changes a value you have. |
| `make check` | Check `.env` (syntax, values, mode, owner, not tracked by git, no secret in a tracked file). Prints every problem and no secret. |
| `make build` | Check, then fetch the pinned frappe_docker checkout and build the image. |
| `make up` | Check, build, then start the stack in the background. A bad key stops it before anything is built. |
| `make down` | Stop the stack. Volumes (database, site files) are kept. |
| `make ps` | Show all containers of the stack. |
| `make logs` | Last 100 log lines per service. |
| `make tools CMD=<command>` | Run a tools command in the tools container. Today: `init`, `whoami`, `config check [--for up\|tools-authentik]`, `config show` (secrets as `*****`), `config sample`. |

Tests, run from `tools/`: `uv run pytest` runs the unit tests. `uv run pytest -m integration` runs the stack tests, which need the stack running and a `.env`. They rerun `create-site` against your live site, which keeps it and changes nothing except pending migrations.

Planned in spec 0003 (not built yet): `make hooks`, `make lint`, `make fmt`, `make test`.

## 5. Layout

- `deploy/`: compose file, image build, version pins, container scripts.
- `tools/`: Python package for setup scripts.
- `apps/nile_auth/`: custom Frappe app (login rules from Authentik groups).
- `content/`: courses. `brand/`: brand assets (do not edit). `docs/`: scope, specs, reviews.

## 6. Keeping this file current

This README is updated at the end of every work turn that changes how the repo is set up or used. See the rules in [AGENTS.md](AGENTS.md).
