# 0002. Keep every setting and secret in one `.env` file, with a key list in code

**Date**: 2026-11-01
**Status**: Accepted

## Summary

All settings and secrets live in one file, `.env`, at the repo root. It is never committed. A committed `.env.sample` lists every key with no secret values in it. A key list inside the Python tools package is the single source of truth: it generates the sample, checks the real file, and decides which keys each container receives. Passwords and keys are generated for you the first time, and a check command stops you from leaking or mistyping them.

## Context

Requirement 6 says all secrets and parameters live in a single file: master API tokens, the app URL, and so on. Spec 0001 already fixed the format (a dotenv file, because Docker Compose can only read that format), the location (repo root), that it is not committed, and that a sample lists every key. It left the details to this feature: the name, the key names, how each container gets its values, and what protects the file.

The file will hold the database root password, the Frappe `encryption_key` (which encrypts every password field, so a restore is impossible without it), the service user's API key and secret, and the Authentik master API token. Two programs read the same file with different rules: Docker Compose (which expands `$` and treats quotes its own way) and Python. A line that one reads differently from the other produces a bug that shows up late, such as a wrong password at first start.

Several later features add settings (Authentik OIDC, backup, SMTP, branding). Without one owner for the key list, keys drift between the code, the compose file, and the sample. Some keys are frozen after the first start: MariaDB ignores a changed root password once its volume exists, and a changed `encryption_key` makes stored secrets unreadable.

This design assumes spec 0001 (Proposed). The build starts after the scaffold sub task of feature 1, because it extends the scaffold's `tools` package and compose file.

## Requirements

**User stories**:
- As the operator, I want one file to edit so that I never hunt through scripts and compose files for a setting.
- As the operator, I want passwords and keys generated for me, and a check that tells me what is missing, so that setup does not depend on my memory.
- As the operator, I want a mistake such as a quoted value, a stray `$`, or a committed secret caught before it causes damage.
- As a developer adding a feature, I want one place to declare a new key so that the sample, the checks, and the container wiring follow.

**Acceptance criteria**:
- **AC-1**: `.env.sample` is generated from the key list and lists every key exactly once, with a short comment per key and group. Every secret key is blank in the sample. Every `${KEY}` used in a compose file exists in the key list.
- **AC-2**: `.env` is ignored by git. `tools config check` fails if `.env` is tracked, if its file mode is wider than 0600, if its owner is not the operator, or if any tracked file contains a current secret value from `.env`.
- **AC-3**: On a clean checkout, `tools init` creates `.env` from the sample with mode 0600 owned by the operator, fills every blank generated secret, and prints the required operator keys still blank (optional ones listed separately). A second run changes nothing, byte for byte, and does not rewrite the file. It never alters a key that already has a value.
- **AC-4**: Through the wrapper (`make up`), a required key that is missing or invalid stops the run before any build or container start, naming every bad key at once with no secret value printed.
- **AC-5**: A value outside the allowed syntax is rejected with its line number. Any accepted value reads identically in Compose (`docker compose config`) and in the tools package.
- **AC-6**: The environment variable names each service receives match the delivery table. No secret value appears in any service's `docker inspect` output except in the entries the table lists. Non secret values (hostnames) may appear in labels and `extra_hosts`. `tools` is inspected as a `run` container without `--rm`, and it holds no secret in its environment.
- **AC-7**: No secret value appears in tools output, logs, or error messages. `tools config show` prints a set secret as `*****` and a blank one as `(blank)`.
- **AC-8**: No image contains any value from `.env`. Build arguments come only from the committed `deploy/versions.env`.
- **AC-9**: If `.env` is lost and regenerated while volumes exist, `create-site` and `ensure_service_user` fail with a clear message when the encryption key or the existing API key differs from the stored one. Nothing is silently kept or replaced.

## Options considered

### Option 1: One `.env`, key list in code, strict syntax, explicit delivery

A dotenv file plus a Python key list that generates the sample, validates the file, generates secrets, and drives which keys each service gets. Compose receives per service `environment` entries, not the whole file.

**Pros**:
- One declaration per key gives the sample, the checks, and the wiring, so they cannot drift.
- A container only holds the secrets it uses.
- No new dependency or service.

**Cons**:
- A new key means a code change, a compose line, and a regenerated sample.
- Strict syntax means some values (a regex, a password with `$`) cannot be written as they are.

### Option 2: Plain `.env` and `env_file` on every service, no tooling

Hand written sample, `env_file: .env` everywhere, each script reads what it needs.

**Pros**:
- Least code, fastest to start.

**Cons**:
- Every container, including nginx and redis, holds the DB root password and the Authentik master token.
- Missing keys fail one at a time, mid run. The sample drifts from reality.

### Option 3: Encrypted file in git (SOPS or similar) or a secrets manager

Secrets are kept encrypted and decrypted at deploy time.

**Pros**:
- Secrets can be versioned and shared safely.

**Cons**:
- Adds a key to manage and a tool to run on a one operator dev server.
- Breaks the plain "one file" requirement and the dotenv path Compose needs.
- Production environment is deferred, so this solves a problem not yet present.

## Decision

**Chosen option**: Option 1: one `.env`, key list in code, strict syntax, explicit delivery.

Use a repo root `.env` (sample: `.env.sample`) owned by a key list in `tools/`, which generates the sample, validates and initializes the file, and defines which keys each compose service receives.

**Implementation skills**: `uv` (`astral-sh/claude-code-plugins`, `.claude/skills/uv/`) · `docker-compose-patterns` (`docker/skills`, `.claude/skills/docker-compose-patterns/`)

## Rationale

The forces are the number of secrets, the two readers with different rules, and the frozen keys. Option 1 puts the knowledge in one list, so the sample, the checks, and the container wiring cannot disagree, and each container holds only what it uses. Option 2 is cheaper to write but gives the Authentik master token to every container and fails late. Option 3 answers a team and production problem this project does not have yet, and the production environment is deferred; if it comes, the key list gives a clean place to add a second source.

The engineer chose the recommended picks on file name (`.env`), key naming (area prefix), delivery (explicit per service), syntax (strict subset with a checker), loader (plain Python module), init behavior, app settings via backend environment, the drift test, log masking, the git guard, and keeping the file out of backups.

Decisions made while writing this spec (not asked):
- **Hostname keys, not URL keys** (runner up: URL keys). Compose cannot parse a URL, and `extra_hosts` needs the bare hostname, so a URL key would create a second source for one fact. Both sites sit behind Traefik on HTTPS, so `https://` plus the hostname is derived in code.
- **Student group match by prefix and suffix** (retired by spec 0009: a learner's course group is matched to a course title in code, so the two keys are gone).
- **The sample is generated from the key list, and a test compares it** (runner up: a hand written sample plus a key set test). Same guarantee for less upkeep.
- **`tools` mounts the repo root and reads `.env` itself** (runner up: pass keys through its environment). `init` has to create the file, and Compose cannot bind a file that does not exist yet. It also leaves no secrets in the tools container's environment. The mount must be the directory, because an atomic rename fails on a single file mount. The temp file is created in the repo root with mode 0600, synced, then renamed, and its name is in `.gitignore` and `.dockerignore`.
- **A root `Makefile` wrapper does the preflight** (runner up: a `preflight` one shot service, rejected: the build runs before it, `up -d` hides its output, and Docker ignores `depends_on` after a reboot). Targets: `init`, `check`, `up` (runs `check`, then `build`, then `up -d`), `down`, `tools`. Compose expands the whole file on every command, so `:?` checks would make `tools init` fail on a clean clone; the wrapper checks instead. The tools image builds with no `.env`.
- **Compose runs from the repo root** with `--project-directory .` (runner up: a copy of `.env` in `deploy/`, or moving `compose.yaml` to the repo root, which is simpler but changes spec 0001). Compose reads `.env` from the project directory. The wrapper hides the long command.
- **Version pins live in a committed `deploy/versions.env`**, not in `.env`. The wrapper passes `--env-file deploy/versions.env --env-file .env`. A pin bump then reaches every checkout, git history records what is deployed, and restoring an old `.env` cannot restore old pins.
- **The wrapper refuses to run if any key from the list is exported in the shell**, because Compose lets the shell win over `.env` while tools reads only the file.
- **The wrapper runs tools as the operator**: `docker compose run --user "$(id -u):$(id -g)"` (bash does not export `UID`). The tools image works under any uid (writable `HOME`, uv cache). The repo is mounted at the same absolute path as on the host, so a git worktree's `.git` pointer resolves, and git gets `safe.directory` set. If git still cannot run, the git checks are skipped with a clear message.
- **Group names go into the Frappe site config**, written by `create-site`, and `nile_auth` reads them from `frappe.conf` (runner up: environment on `backend` only, which misses workers and `bench console`).
- **The compose project name is fixed in the compose file** (`name: nile-lms`), not in `.env`, because changing it creates fresh volumes and looks like data loss.
- **Values owned by another system are not in the file.** The OIDC client id and secret belong to Authentik and Frappe, and the script reads them back, so feature 6 does not copy them here.

## Feature design

**Data model sketch** (the key list, one record per key, in `tools/`):

| Field | Meaning |
|---|---|
| `name` | Env var name, area prefix then purpose, upper case |
| `group` | Section heading in the sample (LMS, DB, AUTHENTIK, TRAEFIK, BUILD, later BACKUP, SMTP) |
| `description` | One line written into the sample as a comment |
| `secret` | True means masked in all output and blank in the sample |
| `required_for` | Where blank fails: `up`, `tools-lms`, `tools-authentik`, or none (optional). `AUTHENTIK_API_TOKEN` is not needed for `up`, so the LMS can start before the token exists |
| `validator` | Per key shape check: hostname (RFC 1123), email shape, exactly 32 hex characters, 44 characters that urlsafe base64 decode to 32 bytes, letters only for group prefix and suffix |
| `source` | `operator` (typed in), `generated` (made by `tools init`), or `default` (sample carries a value) |
| `generator` | For `generated`: how the value is made (below) |
| `default` | Value written to the sample, never for a secret |
| `frozen` | True means fixed after the first start (see invariants) |
| `services` | Compose services that receive it as an environment entry, or none |

Syntax of a value, checked on every read: matches `[A-Za-z0-9_.:/@+=,-]*`, so no quotes, spaces, `$`, `#`, or backslash. One `KEY=value` per line, comment lines start with `#`, no inline comments, no multiline values. Also rejected, each with its line number: `export KEY=`, a line with no `=`, duplicate keys, CRLF line ends, a BOM, trailing spaces, and unknown keys (typos). `COMPOSE_*` keys are the only allowed extras.

Generators: passwords and tokens use `secrets.token_urlsafe(24)`, regenerated until the first character is a letter or digit (a leading `-` could be read as a command flag). `LMS_API_KEY` and `LMS_API_SECRET` use `secrets.token_hex(16)`. `LMS_ENCRYPTION_KEY` uses `base64.urlsafe_b64encode(os.urandom(32)).decode()`, the Fernet key format Frappe expects, built with the standard library only.

**Key inventory** (keys known now; later features add theirs in the same change that needs them):

| Key | Secret | Source | Frozen | Purpose |
|---|---|---|---|---|
| `LMS_HOSTNAME` | no | operator | yes | Public hostname. Site name, Traefik host rule, `host_name`, tools base URL |
| `LMS_ADMIN_PASSWORD` | yes | generated | yes | Frappe `Administrator` password |
| `LMS_ENCRYPTION_KEY` | yes | generated | yes | Frappe site `encryption_key` |
| `LMS_SERVICE_USER` | no | default `nile-tools@example.com` | yes | Service user id (email shaped) |
| `LMS_TIMEZONE` | no | default `America/Los_Angeles` | no | Site timezone, an IANA name. `create-site` writes it to System Settings at every start, so a batch gets this timezone and not Frappe's `Asia/Kolkata` fallback |
| `LMS_API_KEY` | yes | generated | yes | Service user API key |
| `LMS_API_SECRET` | yes | generated | yes | Service user API secret |
| `DB_ROOT_PASSWORD` | yes | generated | yes | MariaDB root password |
| `AUTHENTIK_HOSTNAME` | no | operator | no | Authentik hostname (URL is `https://` plus this) |
| `AUTHENTIK_API_TOKEN` | yes | operator | no | Authentik master API token |
| `AUTHENTIK_APP_SLUG` | no | default `nile-lms` | yes | Slug of the Authentik application the script creates |
| `AUTHENTIK_AUTHORIZATION_FLOW` | no | default `default-provider-authorization-implicit-consent` | no | Slug of the Authentik authorization flow the LMS provider uses; must have no policy bindings that deny students (spec 0008 amendment) |
| `AUTHENTIK_ADMIN_GROUP` | no | default `hol-admins` | no | Group that becomes admin (copied to site config by `create-site`) |
| `TRAEFIK_NETWORK` | no | default `traefik` | no | External Docker network |
| `TRAEFIK_ENTRYPOINT` | no | default `websecure` | no | Traefik entrypoint |
| `TRAEFIK_CERT_RESOLVER` | no | default `letsencrypt` | no | Traefik certificate resolver |

**Not in `.env`: the pins.** `BUILD_FRAPPE_TAG`, `BUILD_LMS_TAG`, `BUILD_FRAPPE_DOCKER_TAG`, `BUILD_PYTHON_VERSION`, `BUILD_NODE_VERSION`, `DB_IMAGE`, and the base image digests live in the committed `deploy/versions.env` (set at scaffold), under the same key list and syntax rules, so spec 0001's reproducible build holds. Both files are listed in the key list; `source` is `committed` for these.

Reserved prefixes: `BACKUP_*` (feature 14), `SMTP_*` (feature 15, SMTP password is a secret).

**File states**:
absent → `tools init` → created (generated keys filled, operator keys blank) → complete (operator filled, `config check` passes) → in use (frozen keys now fixed once `create-site` has run).

**Interface (tools commands, run through the wrapper: `make tools CMD=<command>`)**:

| Command | Does | Errors |
|---|---|---|
| `init` | Creates `.env` from the sample at mode 0600, fills blank generated secrets, writes atomically, keeps comments and order. On an existing file it appends keys added since (under their group heading), never reorders, and does not rewrite the file if nothing changed. Prints required operator keys still blank, optional ones separately | Exit 1 if the file has a syntax error. Never overwrites a value |
| `config check` | Syntax subset, per key validators, keys required for the chosen scope (`--for up` or `--for tools-authentik`), unknown keys, file mode and owner, `.env` tracked by git, tracked files containing a secret value (`git grep -F` over the index and working tree, not history, skipping values under 16 characters, reporting file:line only), sample matches key list | Exit 1 listing every problem, with line numbers, no secret values |
| `config show` | Prints all keys, a set secret as `*****` and a blank one as `(blank)` | None |
| `config sample` | Prints the sample generated from the key list | None |

**Delivery to services** (explicit `environment` entries, nothing else):

| Service | Keys it receives |
|---|---|
| `db` | `DB_ROOT_PASSWORD` (as `MARIADB_ROOT_PASSWORD`) |
| `create-site` | `LMS_HOSTNAME`, `DB_ROOT_PASSWORD`, `LMS_ADMIN_PASSWORD`, `LMS_ENCRYPTION_KEY`, `LMS_SERVICE_USER`, `LMS_TIMEZONE`, `LMS_API_KEY`, `LMS_API_SECRET`, `AUTHENTIK_ADMIN_GROUP` (it writes the admin group into the site config). Commands reference them as `$$VAR` so Compose does not copy the value into the container command |
| `frontend` | `LMS_HOSTNAME` (as `FRAPPE_SITE_NAME_HEADER`) |
| `tools` | None in its environment. It mounts the repo root (same absolute path as on the host) and reads `.env` itself (process environment wins over the file, for tests) |
| `backend` and all other services, `configurator`, redis services, `websocket`, `queue-short`, `queue-long`, `scheduler` | None |

Keys also used by Compose itself for interpolation (image tags, Traefik labels and network): `LMS_HOSTNAME`, `TRAEFIK_*`, and the pins from `deploy/versions.env`. Where Compose would fail to parse an empty value (such as a label), use `${KEY:-unset.invalid}`; this is a parse placeholder, not a default, and the wrapper's check blocks `up` anyway. Defaults live in the sample (or `versions.env`) only, never repeated in compose. The `db` healthcheck uses the image's `healthcheck.sh`, not a command that needs the password under another name.

**Value sourcing**:

| Action | Value produced / displayed | Source |
|---|---|---|
| Traefik label | Host rule | `LMS_HOSTNAME`, interpolated |
| `create-site` | Site name, `host_name` (`https://` + hostname) | `LMS_HOSTNAME` |
| `create-site` | Administrator password | `LMS_ADMIN_PASSWORD` |
| `create-site` | `encryption_key` in site config | `LMS_ENCRYPTION_KEY` |
| `ensure_timezone` | Timezone name | `LMS_TIMEZONE` from the container environment |
| `ensure_service_user` | User id, API key, API secret | `LMS_SERVICE_USER`, `LMS_API_KEY`, `LMS_API_SECRET` from the container environment |
| `tools` API calls | Base URL and `Authorization: token key:secret` | `https://` + `LMS_HOSTNAME`, `LMS_API_KEY`, `LMS_API_SECRET` |
| `tools` Authentik calls | Base URL and bearer token | `https://` + `AUTHENTIK_HOSTNAME`, `AUTHENTIK_API_TOKEN` |
| `nile_auth` | Which group means admin or student | Site config (`frappe.conf`), written by `create-site` from `AUTHENTIK_ADMIN_GROUP`, prefix and suffix keys |
| Image build | Frappe, LMS, Containerfile, Python, Node pins, MariaDB image | `deploy/versions.env` |
| `db` | Root password | `DB_ROOT_PASSWORD` |
| `tools init` | Every generated secret | Generators in the key list |
| OIDC client id and secret | Not in the file | Authentik, read back by the script (feature 6) |
| Compose project name | `nile-lms` | Fixed in the compose file |

**Key invariants**:
- One declaration per key, in the key list. The sample, the checks, and the compose wiring come from it or are tested against it.
- `tools init` only fills blank generated keys. It never changes, rotates, or removes a key that has a value.
- Frozen keys are never changed after the first start. The sample comments mark them "fixed after first start", and `config check` prints the frozen key names as a reminder. Changing one is a manual restore style operation, not an edit.
- Secrets exist only in `.env`: not in the compose file, `apps.json`, build arguments, image layers, tracked files, or output.
- The file is written atomically at mode 0600 and read with the strict syntax only.
- If the stored encryption key or an existing service user key differs from the env value, `create-site` and `ensure_service_user` fail loudly; they never keep or replace it silently. `create-site` writes `encryption_key` into the site config before any app is installed, and it skips creation when the site folder exists. A `sites/.creating-<site>` marker, held from the start of a first creation until setup finishes, makes the next run drop the partial site and start again. `.created` records a finished setup. It is never read as a skip rule, so a site made before the markers existed is left alone.
- Adding a key means one change that touches the key list, the generated sample, and any compose entry together.

**Security model**:
- Whoever can read `.env` controls the LMS, so it is owned by the operator account at mode 0600 and never leaves the host except by the operator's own copy.
- The Authentik master token is read only by the `tools` container.
- Containers hold only their listed keys. Values still show in `docker inspect` of those containers, which spec 0001 accepts on this dev server.
- `.dockerignore` excludes `.env` and its temp file, so no build context carries them.
- No compliance scope.

**Configuration required**: the key inventory above. Before first `up` the operator supplies `LMS_HOSTNAME` and `AUTHENTIK_HOSTNAME`. `AUTHENTIK_API_TOKEN` is needed for the Authentik tools commands, not for `up`.

**Critical test scenarios**:
- Happy path: clean checkout, `make init`, fill `LMS_HOSTNAME` and `AUTHENTIK_HOSTNAME`, `make up` starts, verifies **AC-3**, **AC-4**, **AC-6**.
- Idempotent init: run `init` twice, files are identical, verifies **AC-3**.
- Failure case: delete `AUTHENTIK_API_TOKEN` and set `LMS_HOSTNAME="a b"`; `make check` and `make up` both fail before any build, naming both keys and no secret, verifies **AC-4**, **AC-5**, **AC-7**.
- Syntax parity: write a value with `=` and `_`, compare `docker compose config` output with the tools reading, verifies **AC-5**.
- Leak: `chmod 644 .env`, `git add -f .env`, and paste a secret into a tracked file; each makes `config check` fail, verifies **AC-2**.
- Drift: add a key to the list only, or `${NEW}` to compose only; the test fails, verifies **AC-1**.
- Lost file: remove `.env` with volumes present, run `init` and `up`; `create-site` fails on the key mismatch, verifies **AC-9**.
- Shell override: export `LMS_HOSTNAME` in the shell; the wrapper refuses, verifies **AC-5**.
- Delivery: `docker inspect` every service, compare with the table; grep the built image for the DB password, verifies **AC-6**, **AC-8**.

## Build plan

Tracer Bullet: a thin thread with two keys end to end first, then the rest.

1. Key list type, strict parser and writer (all rejection rules), validators, process environment over file precedence, secret masking (logging filter and exception hook; request headers never logged) in one `config` module, satisfies **AC-5**, **AC-7**
2. Thin thread: keys `LMS_HOSTNAME` and `DB_ROOT_PASSWORD` only; `tools init` and `config sample`; committed `.env.sample`; tools image that builds with no `.env`; root `Makefile` (`init`, `check`, `up`, `down`, `tools`) with `--project-directory .`, `--user` and the same path mount; compose wiring for `db` and `frontend`, satisfies **AC-1**, **AC-3**, **AC-6**
3. Full key inventory with generators, the delivery table for every service, `deploy/versions.env` and the second `--env-file`, and `create-site` wiring (key written before app install, `.created` marker, group keys into site config, `$$VAR` in commands), coordinated with the scaffold, satisfies **AC-3**, **AC-6**, **AC-8**
4. `tools config check`: syntax, validators, scope aware required keys, file mode and owner, tracked file and secret scan (git in the image, `safe.directory`, skip with a message if git cannot run), frozen key reminder, wrapper refusal on exported keys, satisfies **AC-2**, **AC-4**, **AC-5**
5. Mismatch guards in `create-site` and `ensure_service_user` (encryption key, existing API key), satisfies **AC-9**
6. `.dockerignore`, `.gitignore` for the temp file, build argument limits, satisfies **AC-8**
7. Tests: key list vs sample vs `${KEY}` in compose files (ignoring `$${}` and handling `:-` and `:?` forms), Compose and tools syntax parity, `init` idempotency, masking, inspect and image grep, satisfies **AC-1**, **AC-3**, **AC-5**, **AC-6**, **AC-7**, **AC-8**
8. Sample file header: first run steps, frozen keys, the rule to keep a private copy of `.env`, satisfies **AC-1**

## Consequences

**Positive**:
- One file and one list make setup, review, and onboarding simple. A later feature adds keys in one place.
- Least privilege per container limits the damage of one compromised service.
- Mistakes (bad syntax, missing keys, committed secrets) are caught before they cause a failure at first start.

**Negative / tradeoffs**:
- Strict syntax forbids quotes, spaces, `$`, and `#` in values. A pasted token or password with those characters is rejected and must be changed at the source.
- Explicit delivery means a compose line per key per service.
- `tools` mounts the whole repo root, including `.env` and `content/`. They are our own trusted image, but they can read every secret.
- The wrapper is the entry point. Running raw `docker compose up` skips the checks, and after a reboot Docker restarts containers without them.
- The tools container writes `.env` as the operator's uid (the wrapper passes `--user`), so the image and its git setup must work under any uid.
- Losing `.env` after the first start makes the data unrecoverable. The `encryption_key` is not in the backup archives on purpose, so the operator must keep a private copy of the file.
- Frozen keys cannot be rotated by this design. Rotation of the API key, admin password, or database root password is not offered.

**Neutral**:
- Spec 0001 said Compose is passed the file with `--env-file`. With `--project-directory .` it finds `.env` itself and the wrapper adds `deploy/versions.env`. This changes the relative paths in the compose file: they are relative to the repo root.
- Spec 0001 lists "Authentik URL" as a config key; here it is `AUTHENTIK_HOSTNAME` and the URL is derived.
- A second environment (deferred) can reuse the key list with another file name.

## Follow-up

- [ ] Amend spec 0001 on its next update: Config file row (name is `.env`), Compose layout (paths relative to the repo root, `name: nile-lms`, `deploy/versions.env` for pins, the wrapper, group names in site config), and Bootstrap contract (hostname keys, not an Authentik URL key).
- [ ] Prove at scaffold time: `bench new-site` has no encryption key flag, so confirm that writing `encryption_key` into the site config before app install works and that a `.created` marker can replace the `site_config.json` skip rule; that Frappe accepts a supplied 32 hex `api_key` and `api_secret` (expected from its auth code, untested); the Fernet key format Frappe expects.
- [ ] Feature 14 (backup) and 15 (email) add their `BACKUP_*` and `SMTP_*` keys to the key list in the same change that uses them. Feature 14 must not put `.env` in archives, and should say so in its restore steps.
- [ ] Feature 6 decides whether any Authentik value beyond the keys above (such as a redirect URI) needs a key, and keeps OIDC client id and secret out of the file.
- [ ] Key rotation for frozen keys is out of scope. Add a feature if it is needed.
- [ ] Add `uv` and `docker-compose-patterns` to the `## Agent skills` section of root `AGENTS.md` (already listed in spec 0001; `/audit` and `/sync` own that file).
