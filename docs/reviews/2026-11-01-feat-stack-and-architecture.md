# Review, feat/stack-and-architecture, 2026-11-01

**Reviewed by**: claude-opus-5-5 (fresh review subagent; author model not recorded)
**Scope**: 31 files (3 modified tracked, 28 untracked, plus the ignored `deploy/versions.env`), branch vs main
**Verdict**: Blocked

## Summary
The branch adds the spec 0001 scaffold: a layered frappe_docker image with LMS, payments and `nile_auth`; one compose file with the one shot services, healthchecks, log rotation and Traefik labels on `frontend` only; a `create-site` script; and a small `tools` package with `init` and `whoami`. The structure follows the spec closely, and the stack is running healthy on this host. One blocker: `.gitignore` ignores the committed version pins (`deploy/versions.env`), so a fresh clone cannot build. Two majors: `create-site` cannot recover from a partly failed first run, and `payments` is pinned to a moving branch.

## Blockers

### 🔴 `deploy/versions.env` is gitignored, so the pins never reach git, `.gitignore:3`
**Problem**: The `*.env` pattern matches `deploy/versions.env` (`git check-ignore -v deploy/versions.env` reports `.gitignore:3:*.env`). Only `.env.sample` is negated. That is why the file is missing from the untracked list. Committing this branch as it stands leaves the pins out.
**Why it matters**: On a fresh clone, `deploy/fetch-upstream.sh:5` reads an empty tag, and compose fails with `service "redis-cache" has neither an image nor a build context specified` (reproduced with `docker compose config` and no versions file). This breaks spec 0001 AC-4 (reproducible rebuild from the repo) and spec 0002's rule that pins live in a committed `deploy/versions.env`. The README says the file is committed, which is not true.
**Suggested fix**: Add `!deploy/versions.env` to `.gitignore`, or narrow `*.env` to the real secret file names. Confirm with `git check-ignore` and `git status`. Consider a test or `make` preflight that fails if `deploy/versions.env` is not tracked.

## Major

### 🟠 `create-site` cannot recover from a partly failed first run, `deploy/scripts/create-site.sh:10-27`
**Problem**: The script decides whether to skip creation by checking that `site_config.json` exists. `bench new-site` writes that file early, before the database install finishes. The script then sets `encryption_key` in a separate later command. If `new-site` fails partway, or the container stops between line 16 and line 18, the next run sees `site_config.json`, skips creation, and either fails the encryption key check forever (the stored key is missing or auto generated, so it differs from `.env`) or carries on against a half built site.
**Why it matters**: AC-1 needs a clean, repeatable bring up. Here a single interrupted first `up` leaves the stack stuck, and fixing it means deleting volume contents by hand. Spec 0002 (key invariants, build plan step 3) already says to skip on a `.created` marker written at the end, and to write `encryption_key` before any app is installed.
**Suggested fix**: Skip on a `.created` marker (for example `sites/<site>/.created`) written only after `install-app` and `ensure_service_user` succeed. When a site directory exists without the marker, fail with a clear message telling the operator how to reset it, or drop and recreate the site. Keep the mismatch check only for marked sites.

### 🟠 `payments` is pinned to a moving branch, `deploy/apps.json:2`
**Problem**: `{"url": "https://github.com/frappe/payments", "branch": "version-16"}`. Spec 0001 says "A branch name moves, so only tags are pinned", and the Decision now names `payments` as a required image input.
**Why it matters**: Two builds from the same commit can contain different `payments` code. That undermines AC-4 and can break `bench migrate` after a rebuild with no change on our side. `CACHE_BUST` only hashes `apps.json`, so a rebuild either reuses a stale layer or picks up new upstream code without warning.
**Suggested fix**: Pin to a release tag if `payments` publishes one. If not, pin a commit (for example, clone at the branch, then `git checkout <sha>` in the builder stage, or point at a fork tag), and record the exception in spec 0001.

## Minor

### 🟡 Secrets passed as command arguments, `deploy/scripts/create-site.sh:14-15,18`
**Problem**: `--db-root-password "$DB_ROOT_PASSWORD"`, `--admin-password "$LMS_ADMIN_PASSWORD"` and `set-config encryption_key "$LMS_ENCRYPTION_KEY"` put secret values in the process command line, which every host user can read through `ps` while the command runs.
**Why it matters**: Spec 0001 keeps `ensure_service_user` off command arguments for this reason. The exposure is short and the server is a dev host, but the encryption key is the most sensitive value in the system.
**Suggested fix**: Write `encryption_key` into `site_config.json` with a small Python step that reads the environment. For `new-site`, check whether Frappe can read the root and admin passwords from the environment or from config, and otherwise document the accepted exposure.

### 🟡 `.env.tmp` is not gitignored, and its mode is not enforced, `tools/src/nile_tools/cli.py:51-54`
**Problem**: If `init` crashes between the write and the `replace`, `.env.tmp` stays in the repo root holding every secret. `git check-ignore .env.tmp` matches nothing, so `git add -A` would commit it. `touch(mode=0o600)` also leaves an existing temp file's wider mode unchanged. Neither file is fsynced. `init` never tightens an existing `.env` that has a wider mode.
**Why it matters**: Spec 0002 requires the temp file name in `.gitignore`, a 0600 atomic write, and an fsync. A secret in git is the failure this project ranks worst.
**Suggested fix**: Add `.env.tmp` to `.gitignore`. Create the temp file with `os.open(..., O_CREAT|O_EXCL|O_WRONLY, 0o600)` (removing a leftover first), fsync, then rename.

### 🟡 `tools/` does not yet follow the AGENTS.md code rules, `tools/src/nile_tools/cli.py:14-87`
**Problem**: Public functions (`read_env`, `init`, `whoami`, `main`) have no docstrings, and the module has no `__all__`. `GENERATED` is a mutable module-level dict. A missing key raises a bare `KeyError` traceback (`whoami`, line 64), and `tests/test_cli.py:217` locks that behavior in. A blank `LMS_HOSTNAME` builds `https:///api/...` and retries for 5 minutes instead of failing fast with the key named. `pyproject.toml` has `requires-python = ">=3.12"` with no upper bound and no Ruff or mypy config.
**Why it matters**: AGENTS.md asks for one consistent error type that names the config key, fail-fast validation, a deliberate public surface, and no module-level mutable state. Most of this is planned under specs 0002 and 0003, but the scaffold is what later code will copy.
**Suggested fix**: Make `GENERATED` a `MappingProxyType` or a tuple of pairs. Add a `ConfigError` raised when a required key is blank, naming the key. Add docstrings and `__all__`. Leave the full validator to spec 0002.

### 🟡 `init` reports only `LMS_HOSTNAME` as still blank, `tools/src/nile_tools/cli.py:57-58`
**Problem**: The README tells the operator to set `AUTHENTIK_HOSTNAME` and `AUTHENTIK_API_TOKEN` too, but `init` names only `LMS_HOSTNAME`.
**Suggested fix**: List every blank operator key, with optional keys shown separately (spec 0002 AC-3).

### 🟡 Departure from the spec on `tools` `extra_hosts`, not recorded, `deploy/compose.yaml:215-218`
**Problem**: Spec 0001's Script runtime row maps both the LMS and Authentik hostnames to `host-gateway`. The compose file maps only Authentik, and a comment explains that the LMS is reached through Cloudflare because Traefik serves a Cloudflare Origin certificate. The comment also conflicts with `tls.certresolver: ${TRAEFIK_CERT_RESOLVER}` (letsencrypt) on line 162.
**Why it matters**: The real network path differs from the spec, and AC-3 now depends on public DNS and Cloudflare. Later features will design against the spec.
**Suggested fix**: Amend spec 0001 (Script runtime and Reverse proxy rows) to record the Cloudflare path and say which certificate Traefik actually serves. Drop the certresolver label if it is unused.

### 🟡 Build inputs that float outside AC-4, `deploy/Containerfile:59,61,86`, `tools/Dockerfile:3`
**Problem**: `pip3 install frappe-bench` is unpinned, `nvm install 24` takes whatever Node 24.x is current, the nvm installer is piped from a tag URL with no checksum, and the uv image is pinned by tag, not digest. Apt packages float too, which is the upstream norm.
**Why it matters**: AC-4 names only the Frappe, LMS and custom app versions, so this is not a spec breach. But a new `frappe-bench` release can change how `bench init` behaves and break a rebuild.
**Suggested fix**: Pin `frappe-bench==x.y.z` and an exact Node version in `versions.env`, and pin the uv image by digest.

### 🟡 `nile_auth` version is declared in three places with no check, `deploy/versions.env:11`, `apps/nile_auth/pyproject.toml:7`, `apps/nile_auth/nile_auth/__init__.py:1`
**Problem**: The image tag uses `BUILD_NILE_AUTH_VERSION`, and only a comment says it must match the app's own version.
**Suggested fix**: Add a unit test that compares the three values, or derive the tag from the pyproject in the Makefile.

### 🟡 No tests for the branching logic in deploy scripts and `ensure_service_user`, `deploy/scripts/create-site.sh`, `apps/nile_auth/nile_auth/setup.py:11-44`
**Problem**: The key mismatch guard, install-if-missing loop, service user create-or-verify path and healthcheck scripts have no automated coverage. Today they were checked only by `/check verify` on a live stack.
**Suggested fix**: Add `integration`-marked tests (or a `make test-int` target, per spec 0003 Follow-up) that rerun `create-site` and assert it changes nothing, and that a changed key fails it. Unit test `healthcheck-process.py` matching against a fake `/proc` tree.

## Nits
- ⚪ `deploy/scripts/healthcheck-process.py:8`, `open()` without a context manager. Use `Path(path).read_bytes()`.
- ⚪ `deploy/compose.yaml:35`, `--innodb-snapshot-isolation=OFF` is not among spec 0001's flags. Add a one-line comment saying why (upstream frappe_docker with MariaDB 11.8).
- ⚪ `Makefile:5`, on a clean clone `make init` prints about 17 "variable is not set" warnings, which looks like failure. Consider setting `COMPOSE_IGNORE_ORPHANS` or passing `.env.sample` as a fallback env file for `init`.
- ⚪ `tools/` has no `.dockerignore`, so a local `tools/.venv` goes into the build context.
- ⚪ `apps/nile_auth/pyproject.toml:9`, `requires-python = ">=3.10"` while the image runs 3.14, and there is no `[tool.ruff]` block yet (spec 0003).

## Strengths
- Close to the spec: Traefik labels and the external network only on `frontend` with `traefik.docker.network`, no published ports, `service_healthy` and `service_completed_successfully` ordering, `json-file` rotation on every service, base images and DB/redis by digest, and a local image with `pull_policy: never`.
- Careful secret handling in the image path: `apps.json` goes in as a BuildKit secret, the root `.dockerignore` is a deny-all allowlist, `tools` holds no secrets in its environment, and `ensure_service_user` reads from the environment and fails loudly on a key mismatch instead of overwriting.
- `create-site` installs apps after writing `encryption_key` (better than spec 0001's `--install-app` on `new-site`), always runs `migrate`, and checks the stored encryption key.
- `tools` unit tests are well isolated: `tmp_path`, a fake clock, no network, and explicit checks that no secret is printed.

## Test coverage
`tools/tests/test_cli.py` covers `init` (generation, 0600 mode, idempotency, no overwrite, no secret in output) and `whoami` (success, retry, 5-minute timeout naming the URL, no credential leak) well. The tests could not be run here because `uv` is not on PATH in this environment. Untested: the `.env.tmp` crash path, a blank hostname, the `create-site.sh` branches, `ensure_service_user`, and the healthcheck scripts. The shell and Frappe code needs `integration`-marked tests against a live stack.
