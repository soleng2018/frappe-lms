# 0001. Run Frappe LMS as a frappe_docker stack with a Python tools container

**Date**: 2026-11-01
**Status**: Accepted

## Summary

Frappe LMS runs as a set of Docker containers built from the official frappe_docker images, with MariaDB, redis, an nginx front container, and one small custom Frappe app that decides who may log in and with which role. One compose file in this repo defines everything, and Traefik routes to it using labels. A separate Python "tools" container holds the setup, Authentik, and content sync scripts and talks to Frappe and Authentik over their APIs. Every version is pinned, and every setting and secret lives in one dotenv file, so a rebuild gives the same result.

## Requirements

Light acceptance criteria for the foundation, derived from the chosen stack. The scope feature "Stack & architecture" is done when the scaffold meets them.

**User stories**:
- As the operator, I want one compose file and one config file to bring the whole LMS up so that a rebuild after a server failure is predictable.
- As the operator, I want setup scripts that run the same anywhere so that nothing depends on what is installed on the host.

**Acceptance criteria**:
- **AC-1**: From a clean state, bringing the stack up with the compose file runs the one shot services (`configurator`, `create-site`) to exit code 0 in order, and every long running service then reports healthy.
- **AC-2**: The LMS answers over HTTPS at the hostname from the config file, through the existing Traefik, with working CSS, JS, and socket.io, and no published host ports.
- **AC-3**: The tools container calls `GET /api/method/frappe.auth.get_logged_user` on the public hostname with the service user's API key and secret, and the response names the service user.
- **AC-4**: Rebuilding the image twice from the same config gives the same Frappe, LMS, and custom app versions. Frappe and LMS are pinned to exact release tags, base images by digest, and the custom app by its version in this repo.
- **AC-5**: After a restart of the Docker host or the stack, the LMS comes back without manual steps, and container logs rotate at a fixed size.

## Decision

**Chosen option**: Option 1: frappe_docker official images, layered custom image, one compose file, Python tools container.

Use the frappe_docker layered image (Frappe `version-16` pinned to a release tag, plus LMS (and its required `payments` app), plus one custom app copied from this repo) with MariaDB, dedicated redis containers, and the nginx `frontend`, run from one compose file behind Traefik, and drive all setup through a Python tools container that calls the Frappe and Authentik REST APIs.

**Implementation skills**: `frappe-app-dev` (`frappe/skills`, `.claude/skills/frappe-app-dev/`) · `docker-compose-patterns` (`docker/skills`, `.claude/skills/docker-compose-patterns/`) · `uv` (`astral-sh/claude-code-plugins`, `.claude/skills/uv/`)

## Proposed stack

| Layer | Choice | Reason |
|---|---|---|
| Application type | Monolith: Frappe LMS as the single app, plus one small custom Frappe app | Small team, dev server, one product. Nothing to split. |
| Language | Python for the tools package and the custom app. The custom app runs on the Python version of the Frappe image (the build must check what `version-16` requires, which may be newer than 3.12). The tools image has its own Python 3.12 | Frappe is Python. Decoupling the two avoids a forced version match. |
| Framework | Frappe `version-16` pinned to a `v16.x.y` release tag. LMS pinned to an exact release tag (latest checked: v2.68.0, which allows Frappe >=15.121 and <17) | Current frappe_docker default and where LMS work is going. A branch name moves, so only tags are pinned. **Exception:** `payments` publishes no tags, so `apps.json` pins it to the `version-16` branch. A rebuild with a changed `apps.json` or `CACHE_BUST` can pick up new `payments` code. Accepted for this dev server, and revisited if `payments` starts tagging or the pin bites. |
| Custom Frappe app | `nile_auth` (design in scope feature #7): login hook that reads Authentik groups, sets roles, refuses others. Lives in `apps/nile_auth/` and is copied into the image build and installed from that local path | Frappe has no built in group to role mapping, and refusing at login needs a hook. A local copy needs no git URL or token at build time. `apps.json` carries LMS and `payments` (LMS lists it in `required_apps`, so it must be in the image). |
| Primary DB | MariaDB container, version from the frappe_docker MariaDB override (check that `version-16` accepts it), named volume. Keep the upstream flags `--character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci --skip-character-set-client-handshake` | Supported database for Frappe. Postgres is experimental, so not used. Frappe misbehaves without those flags. |
| Cache and queue | Dedicated redis containers (cache, queue) from frappe_docker | Upstream layout, isolated from other apps on this server. |
| Web serving | `frontend` (nginx, same image) serves `/assets`, proxies to `backend` (gunicorn) and `/socket.io` to `websocket`, and receives the site name through `FRAPPE_SITE_NAME_HEADER` | Gunicorn does not serve static assets, and one entry point removes any path routing in Traefik. |
| Background jobs | Frappe's own `queue-short`, `queue-long`, and `scheduler` containers | Built in to Frappe. Nothing extra to add. |
| Realtime | `websocket` (Socket.IO, port 9000), internal only | Part of the upstream layout. |
| File storage | Docker named volume for site files, shared by `backend`, `frontend`, workers, and scheduler | Frappe default. Backup (scope feature #14) covers it. Any later bind mount must be owned by uid 1000, the user in the Frappe images. |
| Image build | Local build on this server from the frappe_docker layered Containerfile, no registry. Image tag `nile-lms:<lms-tag>-<nile_auth-version>`, `pull_policy: never`. Containerfile source pinned to a frappe_docker release tag, base images pinned by digest, `PYTHON_VERSION` and `NODE_VERSION` set explicitly | One host, so a registry adds a service with no benefit yet. Pinning every input gives AC-4. |
| Compose layout | One `deploy/compose.yaml`. One shots: `configurator` (runs on every `up`), `create-site` (ends with bootstrap and `bench migrate`). Long running: `db`, `redis-cache`, `redis-queue`, `backend`, `frontend`, `websocket`, `queue-short`, `queue-long`, `scheduler`. On demand: `tools` (compose profile `tools`) | One file as the scope says. One shot services make a clean setup reproducible. |
| Ordering and restart | `depends_on` with `service_healthy` for `db` and the redis services and `service_completed_successfully` for `configurator` then `create-site`, then the app services. `restart: unless-stopped` on long running services, `restart: "no"` on one shots. After a reboot Docker ignores `depends_on`, so a few early crash loops until `db` is up are accepted | Gives AC-1 and AC-5 without a supervisor. |
| Reverse proxy and TLS | Existing Traefik v3.5.0. Labels on `frontend` only: `traefik.enable`, `traefik.docker.network=traefik`, `websecure` entrypoint, `letsencrypt` resolver, service port 8080, host rule from the config file. Only `frontend` joins the external `traefik` network | Same pattern as `/home/nova/lms`. The network label avoids random IP picks and intermittent 502s. No ports published. |
| Site identity | Site name equals the public hostname. `create-site` sets `host_name` to `https://<hostname>` in the site config | Frappe picks the site from the Host header, and behind TLS terminating Traefik it would otherwise build `http://` URLs and break the OIDC redirect URI. |
| Auth | Frappe OIDC (Social Login Key with Custom provider) against Authentik, created by the tools container through the REST API, with `bench execute` as the fallback | Requirements 1 and 2. Authentik's own Frappe guide uses this mechanism. REST creation is unverified, so scope feature #6 proves it first. |
| Script runtime | `tools` service in the same compose file, Python 3.12 image, run with `docker compose run --no-deps tools <command>`. Reaches the LMS and Authentik through their public names, with no `extra_hosts` mapping | Same environment everywhere. The first plan mapped both names to `host-gateway` so they would resolve to the host where Traefik listens. **As built, amended by spec 0008:** no name is mapped. The LMS is reached through public DNS and Cloudflare, because Traefik serves a Cloudflare Origin certificate that only Cloudflare trusts. Authentik is reached through public DNS too, because it does not run behind this host's Traefik, which answers 404 for its name (found by the feature 6 probe on 2026-11-04). |
| Python tooling | `uv` with `pyproject.toml` and a lock file, `httpx`, `PyYAML`, `pytest`, `ruff` | Reproducible installs and one project file. Final lint choices belong to scope feature #2. |
| API access from scripts | Public HTTPS hostname, API key and secret of a dedicated service user (`Authorization: token key:secret`). The tools container retries every 5 seconds for up to 5 minutes, then fails with a clear message naming the URL | Engineer's choice. Tests the real path end to end. |
| Config file | One dotenv file at the repo root (name settled in scope feature #3), passed to compose with `--env-file` and read by the tools package. Not committed. A sample file lists every key | Compose can only interpolate dotenv, so YAML or a generated `.env` would break the one file rule. |
| Repo layout | One repo: `deploy/` (compose, image build, `apps.json`), `tools/` (Python package), `apps/nile_auth/` (custom Frappe app), `content/` (courses), `brand/`, `docs/` | One clone rebuilds everything, and content sits next to the code that syncs it. |
| Observability | Docker healthchecks plus `json-file` log rotation (`max-size: 10m`, `max-file: 5`) on every service, one shots included | Matches the sample compose and the scope. A richer stack is scope feature #16. |

**Healthchecks** (upstream images ship none, so the compose file defines them):

| Service | Check |
|---|---|
| `db` | `healthcheck.sh --connect --innodb_initialized` |
| `redis-cache`, `redis-queue` | `redis-cli ping` |
| `backend` | `GET /api/method/ping` with a `Host: <site>` header (Python `urllib` if `curl` is absent) |
| `frontend` | HTTP request to nginx on port 8080 |
| `websocket` | TCP connect to port 9000 |
| `queue-short`, `queue-long`, `scheduler` | Process check for the worker or scheduler |

**Bootstrap contract** (who makes the first credentials, so the build does not invent a source):

| Needed value | Source |
|---|---|
| Site name and public hostname | Config file key, same value in the Traefik rule |
| `Administrator` password, MariaDB root password, Frappe `encryption_key` | Config file keys, generated by `tools init` on first run. `create-site` writes `encryption_key` into the site config. It encrypts the API secret, the OIDC client secret, and every password field, so restore needs it |
| API key and secret for the service user | Generated by `tools init` into the config file. The end of `create-site` runs `bench execute nile_auth.setup.ensure_service_user`, which reads the values from the environment (never from command arguments), creates the user if missing, and never changes an existing key |
| Service user details | Type System User, roles System Manager (to create the Social Login Key) plus the LMS roles content sync needs (confirmed in scope feature #4) |
| Authentik URL and master API token | Config file keys supplied by the operator |
| Pinned versions and image tag | Config file keys |

**Create site rules**:
- Skip creation when the site folder exists. A first creation holds a `sites/.creating-<site>` marker until all setup has finished; a leftover marker means an interrupted first run, and the next run drops that partial site and starts again. A finished run writes `sites/<site>/.created`. A site folder with neither marker is never dropped. Otherwise run `bench new-site` with `--mariadb-user-host-login-scope=%`, the DB root and admin passwords from the config, and `--install-app lms --install-app nile_auth`. On a re-run install any app that is missing.
- Always finish with `bench migrate`, so an image upgrade is applied, and check that the scheduler is enabled on a new site.
- `tools init` only fills missing keys. It never rotates the DB root, admin, API, or encryption values once the volume exists, because MariaDB ignores a changed root password after first start.
- `configurator` re-runs on every `up` to refresh `db_host`, redis URLs, `socketio_port`, and `apps.txt`. Check how current frappe_docker keeps assets from going stale in the volume after a rebuild.

**Key invariants**:
- Only `frontend` carries Traefik labels and joins the `traefik` network. MariaDB and redis are never reachable from it.
- No secret appears in the compose file, the image, or git. Everything comes from the config file. Values still show in container environment through `docker inspect`, which is accepted on this dev server.
- Scripts only change items they created. They never touch other containers on this server or other Authentik items.
- `create-site` is idempotent: running it twice changes nothing.

**Security model**: Students and admins log in only through Authentik. The service user's API key stays in the config file and is used only by the tools container.

**Configuration required**: Key names and format are fixed in scope feature #3. This spec requires the values listed in the bootstrap contract.

## Rationale

Reasoning and options: see [rationale.md](rationale.md).

## Consequences

**Positive**:
- The official frappe_docker path is the best supported way to run Frappe in containers, and upgrades follow its documented flow.
- Everything is rebuildable from this repo plus the config file.
- Python tools match Frappe's language, so the custom app and the scripts share skills and libraries.
- Healthchecks and log rotation come from day one.

**Negative / tradeoffs**:
- About a dozen containers for a small product. Most are upstream defaults, but the operator must understand them.
- Calling the API through the public hostname couples setup to Traefik, DNS, and the certificate being ready, and needs the public name to resolve and the certificate to be ready. A Traefik outage blocks setup and sync, though not the running LMS.
- The custom `nile_auth` app is code to maintain against Frappe upgrades, and its pin is the repo version, not a separate release.
- Creating the OIDC login through REST is unproven and may fall back to `bench execute`, which ties part of the setup to the backend container.
- Frappe `version-16` is newer than most guides. Its Python, Node, and MariaDB minimums must be checked at build time.
- The first credentials are made by `create-site`, not the API, and the config file holds the keys needed to restore (including `encryption_key`), so it must be backed up with care.

**Neutral**:
- No registry means the image is built on this server and is not shared.
- Frappe may expose a built in MCP endpoint (`/api/v2/mcp`). A search result said it is on by default on new sites, and that is unverified. Decide in scope feature #5 whether to leave it reachable through Traefik.
- The `MariaDB/mcp` server the engineer chose to try needs database access. Run it as a container on the private compose network, or skip it. Do not publish the database port.

## Follow-up

- [ ] Scope feature #3 fixes the dotenv key names, the file name, and the `tools init` behavior.
- [ ] Scope feature #6 starts with a quick proof that a Social Login Key can be created through the REST API. If it cannot, record the `bench execute` fallback.
- [ ] Scope feature #4 confirms the LMS role names (recalled but unverified: LMS Student, Course Creator, Moderator, Batch Evaluator) and scope feature #7 designs `nile_auth`.
- [ ] Verify before building: exact current Frappe and LMS tags, the Python, Node, and MariaDB versions `version-16` requires, the MariaDB tag in the frappe_docker override, the current upstream service names and override files, and how assets stay current in the volume after a rebuild.
- [ ] Teachers are not a separate role. `hol-admins` are admins and the only course authors. Revisit if a teacher group appears.
- [ ] The scaffold sub task of this feature derives its steps from `## Proposed stack` at `/develop` time: image build, compose file, healthchecks, Traefik labels, `tools` package skeleton.
- [ ] Add the three installed skills (`frappe-app-dev`, `docker-compose-patterns`, `uv`) to the `## Agent skills` section of root `AGENTS.md` (`/audit` and `/sync` own that file).
- [ ] MCP servers the engineer chose to try, connected by the engineer with `claude mcp add`: the Frappe built in endpoint (once the site is up) and `MariaDB/mcp` (read only, dev only, see Consequences). Declined: the Authentik community server and the `frappe-manager` skill.
- [ ] Installed skills run with full agent permissions, so review each one before relying on it.
