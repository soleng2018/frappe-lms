# 0001 Rationale: Run Frappe LMS as a frappe_docker stack with a Python tools container

## Context

The goal is to certify students for a hands on lab. Students watch a video, follow a lab guide, pass a quiz for each at 80% or higher, and earn a certificate. Managers track progress. Authentication must go through an IDP (Authentik) using OIDC, Frappe must be configured through its API by a script, everything runs in Docker behind the existing Traefik, and all settings and secrets live in one file.

The server already runs Traefik v3.5.0, Authentik 2026.8.5, and many unrelated containers, so this stack must stay inside its own compose project and touch nothing else. Docker 28.4 and Compose v2.39 are present, as are Python 3.12 and Node 24. No Frappe container exists yet, so nothing has to be migrated. The install is a dev environment, a production environment is deferred, and the team is small.

Frappe itself has no built in way to turn IDP group claims into roles, and users created through OIDC get no role by default. Without a decision, the later features (login, roles, content sync, backup) would each pick their own setup and drift apart.

## Options considered

### Option 1: frappe_docker official images, layered custom image, one compose file, Python tools container

Build a custom image from the official layered Containerfile with LMS and one custom app added, run the upstream service layout (configurator, create site, backend, websocket, workers, scheduler, MariaDB, redis) from one compose file, and run all scripts from a Python tools container.

**Pros**:
- The best supported path for Frappe in containers, with documented upgrades.
- Reproducible by pinning tags and commits.
- Tools run the same on any host and need no host installs.

**Cons**:
- About a dozen containers.
- The operator has to learn the upstream service layout.
- The image is built on this server.

### Option 2: One custom image running bench under a process supervisor

One Dockerfile installs bench, LMS, and the database client, and a supervisor runs web, workers, and scheduler in a single container.

**Pros**:
- Fewer containers and a short compose file.

**Cons**:
- Works against Frappe's own deployment model, so upstream docs and community answers do not apply.
- One failing process hides inside one container, which makes healthchecks and restarts coarse.
- Harder to debug and upgrade.

### Option 3: Frappe Cloud or other managed hosting

Hand hosting to a managed Frappe service.

**Pros**:
- No infrastructure to run.

**Cons**:
- Violates the requirement to run everything as containers behind the existing Traefik on this server.

### Option 4: frappe_docker unchanged, with PostgreSQL

The same as Option 1, using the Postgres override because Postgres is already used on this server.

**Pros**:
- One database engine across the server.

**Cons**:
- Frappe Postgres support is reported as experimental, and ERPNext on version 16 with Postgres is reported broken by users. No official statement of LMS support was found.

## Rationale

Option 1 fits the forces in Context: the requirements demand containers, Traefik labels, and API driven setup, and the official frappe_docker layout is the only path where upstream docs, community answers, and upgrades all apply. A small team with a dev server benefits from boring and well documented over clever. Option 2 saves containers but costs debuggability and upgrade support, which matter more over time than a shorter compose file. Option 3 conflicts with the requirements. Option 4 is rejected on database support: MariaDB is the supported database for Frappe, and a certifying system should not rest on an experimental one.

Python for the tools matches Frappe, so the custom app and the scripts share skills and libraries, and Python 3.12 is already on the host. Bash would not hold the sync and idempotency logic, and TypeScript adds a second language to a Python product. Running the tools in a container keeps the environment identical everywhere and avoids host installs.

A custom Frappe app with a login hook handles group to role mapping because the requirement includes refusing users in neither group and applying group changes at the next login. A third party mapping app could not be verified, and a scheduled sync cannot refuse at login. The engineer asked how Frappe distinguishes students and teachers: it does not, because OIDC only proves identity and roles come from Frappe itself. The requirements name only student and admin groups, so `hol-admins` cover both teacher and admin duties.

The engineer chose to call the API through the public hostname, not the internal Docker network (the recommended pick). That tests the real path end to end, at the cost that setup depends on Traefik, DNS, and the certificate being up. This is accepted and recorded in Consequences. Because the API does not exist before the site does, the first service user and its keys come from the one shot `bootstrap` service using values generated into the config file.

Version 16 is chosen over version 15 because it is the current frappe_docker default and where LMS work is going, and LMS v2.68.0 supports both. The support window of version 15 was not confirmed.

## Landscape scan (checked 2026-11-01)

- LMS latest release found: v2.68.0 (then v2.67.1, v2.67.0). LMS `pyproject.toml` allows Frappe `>=15.121.0,<17.0.0`. The page does not state which Frappe version each release was tested on.
- frappe_docker builds a custom image with `apps.json` (list of `url` and `branch`) and `images/layered/Containerfile`, passed as a BuildKit secret. Build args include `FRAPPE_BRANCH` (default `version-16`) and `FRAPPE_PATH`. Compose is generated from `compose.yaml` plus overrides for MariaDB, redis, and no proxy (so Traefik fronts it).
- Upstream services (from search results, not opened): configurator (one shot), create site, backend, websocket on port 9000, `queue-short`, `queue-long`, `scheduler`. Names may differ in the current repo.
- Postgres: reported experimental, no official LMS statement.
- Authentik's guide for Frappe uses a Social Login Key with a Custom provider. Redirect URI pattern `https://<site>/api/method/frappe.integrations.oauth2_logins.custom/authentik`, scopes `openid email profile`. The guide does not mention a groups claim.
- No built in group to role mapping in Frappe. An open feature request exists on the Frappe forum. A third party "OIDC Extended" app appeared in search results only.
- Creating a Social Login Key through REST was not verified in docs.
- REST token auth: `Authorization: token <api_key>:<api_secret>`, keys generated per user, permissions follow that user's roles.
- Backup: `bench --site <site> backup --with-files` covers the database and public and private files (from search results).
- Frappe has a built in MCP endpoint at `/api/v2/mcp`, reported enabled by default on new sites.
- Agent Skills and MCP servers found were offered to the engineer. Installed: `frappe-app-dev`, `docker-compose-patterns`, `uv` (which also covers ruff). Chosen to try: the Frappe built in MCP endpoint and `MariaDB/mcp`. Not chosen: `frappe-manager`, the community Authentik MCP server.

Gaps: Social Login Key creation through REST, exact current tags, Postgres override contents, and the Frappe version 15 support window were not verified.

## References

**Project sources**:
- `requirements.md` (requirements 1 to 8 and the instructions)
- `docs/scope/scope.md` (feature 1 and the Tracer Bullet build approach)
- `/home/nova/lms/docker-compose.yaml` (Traefik label pattern and log rotation)
- Running containers on this server (Traefik v3.5.0, Authentik 2026.8.5)

**Practices & standards**:
- Boring technology first, monolith first for a small team
- Idempotent one shot setup services
- Pin versions for reproducible builds
- Keep secrets out of images and git (BuildKit secrets, one config file)

**Links** (web verified):
- Frappe LMS releases: https://github.com/frappe/lms/releases
- LMS `pyproject.toml`: https://github.com/frappe/lms/blob/main/pyproject.toml
- frappe_docker custom image build: https://github.com/frappe/frappe_docker/blob/main/docs/02-setup/02-build-setup.md
- Authentik integration guide for Frappe: https://integrations.goauthentik.io/development/frappe/
- Frappe REST API authentication: https://docs.frappe.io/framework/user/en/api/rest
