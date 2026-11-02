# Review, feat/stack-and-architecture, 2026-11-01 (re-review)

**Reviewed by**: claude-opus-5-5 (fresh review subagent; author model not recorded)
**Scope**: 37 files, branch vs main (merge base 93e3d2a, commits 78dd9c5 and e3f5575; working tree clean)
**Verdict**: Changes requested

This is the **re-review**. It replaces the first review in this file, which was Blocked. The first review's findings and what happened to each are listed under "Earlier findings" at the end.

## Summary
The branch adds the spec 0001 scaffold: a layered frappe_docker image (Frappe, LMS, payments, `nile_auth`), one compose file with one shot services, healthchecks, log rotation and Traefik labels on `frontend` only, a `create-site` script, and a small `tools` package (`init`, `whoami`) with unit and integration tests. The first review's blocker is fixed: `deploy/versions.env` is now tracked. Every other earlier finding was either fixed or recorded as an accepted exception. The fixes add no new correctness bug on the paths that ran: the live site (which predates the markers) is left alone and now has `.created`, all nine services are healthy with the refactored process healthcheck, and the new Node and bench pins match the running image (`node v24.22.2`, `bench 5.31.1`). One major remains. The new recovery branch in `create-site` (the `.creating-<site>` marker and `drop-site`) is the fix for an earlier major, and no test or manual run has exercised it. Reading it closely shows two gaps around it.

## Major

### 🟠 The interrupted-creation recovery path has never run, `deploy/scripts/create-site.sh:13-17`
**Problem**: The `PENDING` branch (`bench drop-site ... || true`, then `rm -rf "sites/$SITE" "$PENDING"`) is new error handling logic. No unit test, integration test or manual run covers it. The three integration tests only cover the "site exists" branch. The branch also depends on Frappe behavior that has not been checked. `_drop_site` calls `frappe.init(site)` and `frappe.connect()` first (frappe `commands/site.py:1020-1021`). So when `new-site` stopped after writing `site_config.json` but before the DB user existed, `drop-site` fails, `|| true` hides the failure, and the script carries on.
**Why it matters**: This is the fix for the first review's "create-site cannot recover" major. Until it runs once, nobody knows it works. Spec 0001 AC-1 depends on it, and a broken recovery shows up on the worst day: the first install on a new host.
**Suggested fix**: Add an `integration` test that runs `create-site` with a throwaway `LMS_HOSTNAME` (for example `interrupt-test.invalid`). Seed a partial site (`bench new-site` followed by `touch sites/.creating-<site>`, or a site directory that holds only `site_config.json`). Assert the output says "Dropping the partial site", the run exits 0, and the site is recreated. Then drop the throwaway site. A cheaper option is a stub `bench` on `PATH` plus a configurable bench directory (the script hard codes `cd /home/frappe/frappe-bench`), which tests the shell branching without the stack.

## Minor

### 🟡 The pending marker is removed before apps are installed, `deploy/scripts/create-site.sh:43`
**Problem**: `rm -f "$PENDING"` runs right after `enable-scheduler`, before `install-app lms` / `install-app nile_auth`, `migrate` and `ensure_service_user`. If the first run stops during `install-app lms`, the next run takes the "Site exists" branch and calls `install-app lms` again. Frappe adds an app to `installed_apps` only at the end, so a half installed app runs its install again. The LMS `after_install` (`create_batch_source`, permission grants, index creation) and payments `before_install`/`make_custom_fields` have to tolerate a second run. That has not been checked.
**Why it matters**: The recovery window is narrower than before but not closed. On a fresh site, dropping and recreating is cheap and always safe.
**Suggested fix**: On the creation path, keep `PENDING` until the install loop, `migrate` and `ensure_service_user` all succeed. In practice, remove it next to `touch "$MARKER"`, but only when this run created the site. The "exists" path stays as it is, so the legacy live site is still never dropped.

### 🟡 A failed drop is silent, and the dropped site's archive leaks out of the volume, `deploy/scripts/create-site.sh:15`
**Problem**: `|| true` throws away the reason `drop-site` failed. A database and user that were created can be orphaned with no message (the next `new-site` picks new random names, so the orphans just pile up in MariaDB). When the drop does succeed, Frappe moves the partial site to `/home/frappe/frappe-bench/archived/sites/<site>` (`commands/site.py:1049-1056`). That path is in the `create-site` container's writable layer, not a volume. Compose keeps and reuses the exited container, so the archive (holding the DB password, and the encryption key if the heredoc had already run) stays there. `drop-site` also puts `DB_ROOT_PASSWORD` on the command line, and the accepted-exposure comment covers only `new-site`.
**Suggested fix**: On failure, print a warning that names the site's `db_name` from the partial `site_config.json`, so the operator can drop it by hand. Pass `--archived-sites-path` to a temporary directory and delete it afterwards. Widen the accepted-exposure comment to cover `drop-site`.

### 🟡 The skip rule now differs from both specs, and `.created` is written but never read, `deploy/scripts/create-site.sh:12,19,69`
**Problem**: The script skips creation when the site directory exists and treats `sites/.creating-<site>` as "interrupted". It writes `sites/<site>/.created`, but nothing reads it. Spec 0002 line 201 says "its skip rule keys on a `.created` marker, not on `site_config.json`". Spec 0001 line 83 still says to skip on `site_config.json` and pass `--install-app` to `new-site`. The built design is sound, and it is the right choice for the legacy site that has no marker, but no spec records it. Feature 3 (spec 0002) will be built against the old wording.
**Suggested fix**: Record the pending-marker scheme in spec 0001 (as built) and spec 0002 key invariants, through `/architect` or as a flag for `/sync`. Then keep `.created` with its purpose stated (an audit and "setup finished" signal) or remove it.

### 🟡 `init` does not tighten an existing `.env` with a wide mode, `tools/src/nile_tools/cli.py:65-76`
**Problem**: Left over from the first review's `.env.tmp` finding. When nothing needs generating, `init` leaves an existing `.env` at whatever mode it has (for example 0644 after a manual `cp .env.sample .env`). It reaches 0600 only when a generated key was blank. The README says the file "should be mode 0600".
**Suggested fix**: `chmod 0o600` the `.env` on every `init` (or warn), and add a unit test.

## Nits
- ⚪ `deploy/scripts/create-site.sh:7`, add `: "${LMS_HOSTNAME:?LMS_HOSTNAME is blank}"` before any `rm -rf "sites/$SITE"`. The empty case cannot reach the `rm` today, but the guard costs nothing.
- ⚪ `deploy/scripts/create-site.sh:46`, a site directory without `site_config.json` (and no pending marker) ends in a Python `FileNotFoundError` traceback instead of a clear message saying how to reset.
- ⚪ `deploy/scripts/create-site.sh:30-41`, the heredoc truncates `site_config.json` and then rewrites it in place. That is safe today only because `PENDING` covers that window. A temp file plus `os.replace` would hold up if the code moves.
- ⚪ `tools/src/nile_tools/cli.py:94`, the line is 104 columns, over the 100 column rule.
- ⚪ `tools/tests/test_cli.py:3`, Ruff reports I001 (import block unsorted).
- ⚪ `apps/nile_auth/pyproject.toml:9`, `requires-python = ">=3.10"` while the image runs 3.14 (left over from the first review).
- ⚪ `deploy/Containerfile:344`, the nvm installer is still piped from a tag URL with no checksum (upstream norm, left over).

## Strengths
- The fix for the dangerous version is right. The intermediate commit 78dd9c5 keyed on `.created` and ran `new-site --force`, which would have wiped the live site (it had no marker). e3f5575 switched to a positive "creation in progress" marker, so a site with no markers is never dropped. Verified on the live site: it is kept and now has `.created`.
- The pins are checked by tests. `test_every_build_arg_in_compose_has_a_pin` and the three-way `nile_auth` version check stop the gitignored-pins class of bug from coming back. The healthcheck refactor keeps script invocation (`__main__` guard; all three process-checked services are healthy) and adds fake-`/proc` unit tests, including a process that vanished.
- `tools` now meets the AGENTS.md rules: one `ConfigError` that names the key, `__all__`, docstrings, an immutable `GENERATED`, an O_EXCL 0600 temp file with fsync, and tests for each.

## Test coverage
Unit: 33 pass, 3 integration deselected (run here in a venv with `PYTHONPATH=tools/src python -m pytest -c tools/pyproject.toml`). They cover `init` (generation, 0600, a leftover wide temp file, every blank operator key, no secret printed), `whoami` (retry, timeout naming the URL, blank key fails fast), `main` error handling, the version pin checks and the process healthcheck logic. Integration (reported passing against the live stack): a `create-site` rerun keeps the site, a changed encryption key is refused, a changed API secret is refused. Not covered: the `create-site` interrupted-creation branch (Major above), `healthcheck-backend.py`, and `ensure_service_user`'s create path (exercised only by the original bring-up). The Containerfile pin changes have not been rebuilt, but the pinned Node and bench versions match the running image, so the risk is low. A rebuild before merge would confirm AC-4.

## Earlier findings (first review) and what happened to each
| Earlier finding | Status |
|---|---|
| 🔴 `deploy/versions.env` gitignored | **Resolved**: `!deploy/versions.env` in `.gitignore`, the file is tracked, `git check-ignore` no longer matches it |
| 🟠 `create-site` cannot recover from interruption | **Mostly resolved**: pending marker plus drop. Remaining gaps are the Major and the first two Minors above |
| 🟠 `payments` on a moving branch | **Accepted**: the exception is recorded in the spec 0001 Framework row |
| 🟡 Secrets on command lines | **Resolved / accepted**: `encryption_key` is now written from the environment. The `new-site` passwords are a documented accepted exposure (`drop-site` is not covered by that note, see Minor) |
| 🟡 `.env.tmp` not ignored, mode not enforced | **Resolved**: gitignored, O_EXCL 0600, fsync, leftover removed, tested. One leftover: an existing `.env` is not tightened (Minor) |
| 🟡 `tools` code rules | **Resolved**: docstrings, `__all__`, `MappingProxyType`, `ConfigError`. Ruff and mypy config is still planned in spec 0003 |
| 🟡 `init` reports only `LMS_HOSTNAME` | **Resolved**: every blank operator key is listed and tested |
| 🟡 `extra_hosts` spec departure | **Resolved**: spec 0001 Script runtime row amended, and the compose comment explains the certresolver label |
| 🟡 Floating build inputs | **Resolved** (not rebuilt): bench, Node and the uv digest are pinned and match the running image. The nvm installer checksum is still open (Nit) |
| 🟡 `nile_auth` version in three places | **Resolved**: unit test |
| 🟡 Missing tests for deploy logic | **Partly resolved**: healthcheck and pin unit tests, three integration tests. The recovery branch is untested (Major) |
| Nits: `open()`, innodb comment, `make init` warnings, `tools/.dockerignore` | **Resolved** |
| Nit: `nile_auth` `requires-python` | Open |
