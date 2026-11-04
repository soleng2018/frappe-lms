# 0007. Prove the LMS runs behind Traefik and close the gaps

**Date**: 2026-11-03
**Status**: In Progress

## Summary

The LMS already runs behind Traefik: the compose file, labels, restart policy, and log rotation were built with the stack scaffold (spec 0001) and are live and healthy. What was missing is proof you can re run, and three gaps. Plain HTTP is not redirected, the Frappe MCP endpoint (a door for AI agents) is public, and nothing checks a restart. This spec adds one `verify deploy` command, one `restart-test` script, a dedicated MCP user with its own key so your agent can sign in, and a README step for the Cloudflare HTTPS toggle.

## Requirements

**User stories**:
- As the operator, I want one command that proves the LMS is reachable, safe, and healthy over its public hostname so that I can run it after every rebuild.
- As the operator, I want a restart test so that "survives a restart" is shown, not assumed.
- As the operator, I want my AI agent to use the MCP endpoint with its own key so that I can revoke it alone and never hand it the tools key.

**Acceptance criteria**:
- **AC-1**: `verify deploy` checks over `https://<LMS_HOSTNAME>`: `GET /api/method/ping` returns 200 with `{"message":"pong"}`; `GET /` (same host redirects followed, final URL printed) returns 200 HTML, finds at least one CSS and one JS file under `/assets/`, and every one it finds returns 200; `GET /socket.io/?EIO=4&transport=polling` returns 200 with a body that starts with `0{`.
- **AC-2**: A static check of `deploy/compose.yaml` passes only when no service publishes ports, only `frontend` has `traefik.*` labels and the `traefik` network, and the Traefik router rule names `${LMS_HOSTNAME}`.
- **AC-3**: `verify deploy` sends `GET http://<LMS_HOSTNAME>/` without following redirects. A 301, 302, 307, or 308 with a `Location` that starts with `https://` is a PASS. Anything else is a WARN (never a FAIL) that tells the operator to turn on Always Use HTTPS in Cloudflare. The README documents that step.
- **AC-4**: `verify deploy` sends a JSON-RPC `initialize` POST (`protocolVersion` 2025-06-18, `Accept: application/json, text/event-stream`) to `/api/v2/mcp`. Without credentials it must get 401 (status plus the substring `Authentication`). With `Authorization: token <LMS_MCP_API_KEY>:<LMS_MCP_API_SECRET>` it must get 200 with a JSON-RPC `result` (a JSON body or an SSE `data:` line).
- **AC-5**: `create-site` creates the MCP user (System User, Desk User plus the four LMS roles, never System Manager), on a new site and on the existing site path, with the key and secret from `.env`. For this user `.env` wins: a rerun with the same values changes nothing, and a changed `.env` value updates the user's key and secret (rotation is edit `.env`, then `make up`). After insert and on every rerun it re-reads the user and exits with a message, changing nothing further, if `user_type` is not System User, `Desk User` is missing, an LMS role does not exist, or the user holds System Manager. An Authentik login that resolves to that user is refused as protected, with no write. Spec 0006 AC-8 and the `nile_auth` protected list are updated to match in this feature.
- **AC-6**: `make restart-test` restarts only the long running services of the `nile-lms` project, named explicitly, never the one shots. It then simulates a crash of `backend` and `frontend` with `kill -9` on their host PIDs (from `docker inspect`, run with sudo), because `docker kill` marks a container as manually stopped and `unless-stopped` will not bring it back. Within 180 seconds every long running service is healthy again with no manual step, and `verify deploy` then passes. It touches no container outside the `nile-lms` project.
- **AC-7**: Every service in `deploy/compose.yaml` (one shots and `tools` included) has `logging` driver `json-file` with `max-size: 10m` and `max-file: "5"`, and every long running service has `restart: unless-stopped` (static check in `verify deploy`). `restart-test` also reads the live values from `docker inspect` and fails if they differ.
- **AC-8**: `verify deploy` prints one line per check as `PASS`, `WARN`, or `FAIL`, naming the URL or compose key involved. It exits 0 when there is no FAIL. It never prints a secret value. If config keys it needs are missing, it stops first and names every missing key at once.

## Decision

**Chosen option**: Option 2: a Python `verify deploy` command plus a host side `restart-test` script, with the MCP endpoint kept public but behind a dedicated read and write user.

Add `verify deploy` to the `nile_tools` package (public URL checks plus a static compose check, all pure where possible), a `make restart-test` target that drives Docker from the host and then calls `verify deploy`, a dedicated MCP user created by `create-site`, and Cloudflare Always Use HTTPS as the HTTP redirect, documented in the README and watched by a WARN.

**Implementation skills**: `docker-compose-patterns` (`docker/skills`, `.claude/skills/docker-compose-patterns/`) · `frappe-app-dev` (`frappe/skills`, `.claude/skills/frappe-app-dev/`) · `uv` (`astral-sh/claude-code-plugins`, `.claude/skills/uv/`)

## Feature design

**Surface**: no new endpoint on the LMS. The new surfaces are commands.

| Command | Where it runs | Inputs | Output | Errors |
|---|---|---|---|---|
| `make tools CMD="verify deploy"` | `tools` container, public network path | `.env` keys below, `deploy/compose.yaml` from the mounted repo | One result line per check, exit 0 or 1 | Missing keys (named together), network failure (names the URL) |
| `make restart-test` | Host (needs the Docker CLI) | `.env`, project name `nile-lms` from the compose file | Progress lines, exit 0 or 1 | A service not healthy in 180 s (names it), live config differs |

**Checks in `verify deploy`** (each a pure function from the response or parsed compose to a result):

| Check | Level on fail | AC |
|---|---|---|
| ping, home page, asset files, socket.io handshake | FAIL | AC-1 |
| compose: no ports, only frontend labelled and on `traefik`, rule names the host | FAIL | AC-2 |
| plain HTTP redirects to HTTPS | WARN | AC-3 |
| MCP without credentials gives 401 | FAIL | AC-4 |
| MCP with the MCP user's key gives 200 | FAIL | AC-4 |
| compose: logging and restart settings | FAIL | AC-7 |

**Value sourcing**:

| Action | Value produced or displayed | Source |
|---|---|---|
| `verify deploy` | Base URL | `LMS_HOSTNAME` from `.env`, `https://` or `http://` prefix chosen per check |
| `verify deploy` | Asset paths to fetch | Parsed with stdlib `html.parser` from `<link rel=stylesheet or modulepreload href>` and `<script src>` on `/assets/`, query string kept, first 5 of each type. Zero of either type is a FAIL |
| `verify deploy` | Network failure result | One 10 second timeout and a fixed User-Agent. A failed request is WARN for the HTTP redirect check and FAIL for every other check, naming the URL. A Cloudflare challenge 403 is reported as such |
| `verify deploy` | Keys it needs | A `verify` scope in `config.py` SCOPES: `LMS_HOSTNAME` and the three MCP keys, checked together so every missing key is named at once |
| `verify deploy` | Compose facts | `yaml.safe_load` on the raw `deploy/compose.yaml` (handles anchors and merges), host rule compared as the uninterpolated text `` Host(`${LMS_HOSTNAME}`) ``. The tools container has no Docker CLI |
| `verify deploy` | MCP credentials header | `LMS_MCP_API_KEY` and `LMS_MCP_API_SECRET` from `.env`, shown only as `****` |
| `verify deploy` | Expected log values and restart policy | Constants in the verify module: `json-file`, `10m`, `5`, `unless-stopped` (spec 0001) |
| `verify deploy` and `restart-test` | Which services are long running | One pure function over the compose file: a one shot is the target of a `service_completed_successfully` dependency; profile services are excluded; every other service is long running, and one without `restart: unless-stopped` fails. `restart-test` gets the list from the same function |
| `restart-test` | Running containers and their health | `docker ps -q --filter label=com.docker.compose.project=nile-lms`, then `docker inspect` `.State.Health.Status`, polled every 5 s for up to 180 s. Live config from `HostConfig.LogConfig` (all project containers) and `HostConfig.RestartPolicy.Name` (long running only). `tools` is run with `--rm`, so it is checked statically only. No dependence on `docker compose config` or `jq` |
| `restart-test` | Host PID to kill | `docker inspect -f '{{.State.Pid}}'`, killed with `sudo kill -9` |
| `create-site` | MCP user rerun | `ensure_mcp_user` runs on the existing site path too, beside `nile_service_user`, after `ensure_timezone` |
| `restart-test` | Health timeout | Constant 180 seconds in the script (decided here) |
| `restart-test` | Services to kill | `backend` and `frontend` (decided here: the app server and the front door) |
| `create-site` | MCP user id, key, secret | `LMS_MCP_USER`, `LMS_MCP_API_KEY`, `LMS_MCP_API_SECRET` passed as container environment, never as arguments |
| `create-site` | Site config `nile_mcp_user` | Written from `LMS_MCP_USER`, read by the `nile_auth` login to protect the account |

**Key invariants**:
- Only `frontend` carries Traefik labels and joins the `traefik` network. No service publishes a port.
- The MCP user never holds System Manager. The tools service user's key is never used for the agent.
- The login protects `nile_mcp_user`, but the "all settings present" precondition does not require it, so a site without the setting still accepts logins.
- `restart-test` only acts on the `nile-lms` compose project. Other containers on this server are never touched.
- Check output never contains a secret value.

**Security model**: The MCP endpoint stays reachable on the public hostname. Frappe answers Guests with 401 and refuses non System Users with 403. The MCP user is a System User with the Desk User role and the four roles in `LMS_ROLES` (LMS Student, Course Creator, Moderator, Batch Evaluator), which lets the agent read and write LMS content. It cannot change System Settings, users, or roles. The key can be revoked alone by regenerating it in the User record. No personal data class beyond what the LMS holds; no extra compliance scope.

**Configuration required** (new keys, same rules as spec 0002: generated by `tools init`, `(fixed)` after first start):
- `LMS_MCP_USER`: email shaped user id, default `nile-mcp@example.com`, `(fixed)`
- `LMS_MCP_API_KEY`: generated, hex32, not `(fixed)` (rotate by editing `.env`, then `make up`)
- `LMS_MCP_API_SECRET`: generated, hex32, secret, not `(fixed)`
- All three are registered in `config.py` KEYS, required for `up`, passed to `create-site` in compose, and added to the regenerated `.env.sample`. On an existing install `make check` refuses until the operator runs `make init`. Emergency revoke: disable the user in the Desk.

**Critical test scenarios**:
- Happy path: `verify deploy` against the live site passes every check, verifies **AC-1**, **AC-2**, **AC-4**, **AC-7**
- Failure case: a compose copy with a published port or a missing `max-file` fails the static check (unit test, no network), verifies **AC-2**, **AC-7**
- Failure case: HTTP returns 200 instead of a redirect, so a WARN and exit 0, verifies **AC-3**
- Failure case: `.env` lacks the MCP keys, so `verify deploy` names all three at once, verifies **AC-8**
- Restart: `restart-test` kills `backend` and `frontend` and all services return to healthy, verifies **AC-6**
- Auth: the MCP call without credentials returns 401, and an Authentik user matching the MCP user id is refused, verifies **AC-4**, **AC-5**
- Idempotence: `create-site` run twice leaves the MCP user unchanged, and a changed key stops it, verifies **AC-5**

## Build plan

Build approach: Tracer Bullet. First one real check end to end through the CLI and Makefile, then thicken one strand at a time.

1. Thin thread: the `verify deploy` command with the result type, the config check, and the single `ping` check, reached through `make tools CMD="verify deploy"`, satisfies **AC-1**, **AC-8**
2. Public checks: home page and assets, socket.io handshake, plain HTTP redirect WARN, with unit tests on canned responses, satisfies **AC-1**, **AC-3**, **AC-8**
3. Static compose checks: ports, labels, network, logging, restart policy, with unit tests on good and bad compose samples, satisfies **AC-2**, **AC-7**
4. MCP user: first a gate on the live site that Frappe keeps `user_type` System User and `Desk User` for a user with these roles and that `frappe.mcp` accepts it; then config keys in `config.py`, `tools init`, `.env.sample`, `create-site` environment and `nile_mcp_user` site config, `ensure_mcp_user` (runs on new and existing sites, `.env` wins, self checks), `nile_mcp_user` in the `nile_auth` protected check and the spec 0006 AC-8 text, satisfies **AC-5**
5. MCP checks in `verify deploy` (unauthenticated 401, authenticated 200), satisfies **AC-4**
6. `deploy/scripts/restart-test.sh` and the `restart-test` Makefile target (depends on `guard`): restart the long running services, `kill -9` the host PIDs of `backend` and `frontend`, wait for healthy, read live logging and restart values, then run `verify deploy`, satisfies **AC-6**, **AC-7**
7. Live integration test (marked `integration`), `README.md` (prerequisites, the MCP keys, how to connect an agent with `Authorization: token key:secret`, the Cloudflare Always Use HTTPS step, the two commands), and `deploy/AGENTS.md` pointers, satisfies **AC-1** to **AC-8**

## Consequences

**Positive**:
- "Opens over HTTPS, survives a restart, logs rotate" becomes a command you can run, not a belief.
- Your agent gets its own key. Revoking it does not affect the tools container or content sync.
- Config drift in the compose file (a published port, lost log rotation) is caught by a unit test and by the live check.

**Negative / tradeoffs**:
- The agent can write LMS content. Git is the source of truth for content, so an agent edit shows up as drift in `sync --check` and the next `sync` overwrites it. Treat agent writes as temporary.
- The MCP endpoint stays on the internet. A key is the only gate, and there is no rate limit (HSTS and rate limits stay in Deferred).
- The HTTP redirect lives in the Cloudflare dashboard, outside git. A rebuild on another Cloudflare account loses it. `verify deploy` only warns.
- `restart-test` restarts and kills containers but does not reboot the host. Boot behaviour (Docker enabled at startup, containers returning after a crash loop on `db`) is a one time manual note.
- `restart-test` needs the Docker CLI and sudo on the host, so it cannot live in the `tools` container.
- The public checks pass through Cloudflare, so its edge cache could serve an asset while the origin is broken. Accepted; the ping and MCP checks are not cacheable.

**Neutral**:
- This resolves the open item in spec 0001 about the built in MCP endpoint.
- No database schema change, so there is no migration plan.

## Follow-up

- [ ] Feature 7's build is in progress and this feature edits `apps/nile_auth/` login and the 0006 AC-8 text (build step 4). Land it so it does not collide with 0006's open milestone.
- [ ] Do the Cloudflare step once (Always Use HTTPS on the zone) and re run `verify deploy` to clear the WARN.
- [ ] Once, by hand, reboot the host in a quiet window and note the result in the README. Other apps on this server go down too.
- [ ] Add `LMS_MCP_USER`, `LMS_MCP_API_KEY`, `LMS_MCP_API_SECRET` to the spec 0002 key list when feature 3's text is next touched, and connect the agent as the MCP server in the README.
- [ ] Revisit read only access for the agent when feature 12 (manager progress view) starts.

Decision history (context, options, rationale): [rationale.md](rationale.md). Verify steps: [verify.md](verify.md).
