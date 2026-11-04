# Review, feat/course-groups, 2026-11-04

**Reviewed by**: claude-opus-5-5 (fresh review subagent; author model not recorded)
**Scope**: 40 files (24 code, config and test files read closely), branch vs main (plus the uncommitted `tools/tests/test_create_site.py`)
**Verdict**: Changes requested

## Summary
The code on this branch is spec 0007 (LMS behind Traefik). It adds `verify deploy` (public URL checks, MCP checks, a static compose check), `make restart-test`, and a dedicated MCP user with its own key. The login also refuses that user. Specs 0008 and 0009 are only docs (status Proposed), so this branch has no code for them, even though it is named course-groups. `verify.py` is clean: pure judges, the network kept at the edge, no secret in any output line, and good unit coverage. One real gap: the new branch in the login that refuses the MCP user has no test at all, and the spec lists it as a critical scenario. The other findings are small: user id comparisons are case sensitive in some places and not in others, a confusing error path in `ensure_mcp_user`, and `verify` skips the `SCOPES` design the spec asked for. All 482 unit tests pass.

## Major
### 🟠 The login refusal of the MCP user is untested, `apps/nile_auth/nile_auth/login.py:143`
**Problem**: `_refuse_if_protected` has a new branch that refuses a login when it resolves to `nile_mcp_user`, and has a guard for when the setting is blank. No unit test, live script (`tools/tests/live_scripts/group_role_scenarios.pyscript` only covers the service user), or integration test runs this branch. Spec 0007 lists "an Authentik user matching the MCP user id is refused" under Critical test scenarios (AC-5). The verify.md tick is a manual step only.
**Why it matters**: This is the only thing that stops an Authentik account with the MCP user's email from taking over a System User that has an API key and write access to content. A refactor of this condition (for example, the blank guard dropped so `"" == ""` matches, or the `.lower()` removed) would pass every test.
**Suggested fix**: Add a scenario to the group/role live script, as was done for the service user: a login with the MCP user's email is refused as `protected` and the user record is unchanged. Also add one where `nile_mcp_user` is blank, to show that ordinary logins still pass.

## Minor
### 🟡 User id comparisons are case sensitive in setup, but not in the login or the database, `deploy/scripts/create-site.sh:9`, `apps/nile_auth/nile_auth/setup.py:85`
**Problem**: The "must differ from LMS_SERVICE_USER" guards compare the two ids exactly. `login.py` lowercases them, and both Frappe user names and the MariaDB collation ignore case. With `LMS_MCP_USER=Svc@x.com` and `LMS_SERVICE_USER=svc@x.com`, both guards let it through. `set-config nile_mcp_user` then writes, and `frappe.db.exists("User", ...)` finds the service user. Only the System Manager self check stops the service user's key from being overwritten.
**Why it matters**: The AC-5 promise "refuse before anything is written" fails for this input, and the error message (the user "holds System Manager") points the operator the wrong way. The self check saves you today, but only because the service user happens to hold System Manager.
**Suggested fix**: Compare lowercased values in both guards. Or make the config validator refuse two ids that match without regard to case, so `make check` catches it first.

### 🟡 `get_password` raises when an existing MCP user has no secret, `apps/nile_auth/nile_auth/setup.py:93`
**Problem**: On the existing user path, `user.get_password("api_secret")` raises `frappe.AuthenticationError` if the record has no stored secret. This happens when the user was made by hand or its keys were cleared in the Desk. The comment in `ensure_service_user` says `bench execute` hides such exceptions behind a NameError.
**Why it matters**: Rotation is meant to be "edit `.env`, then `make up`". If the secret was cleared, this path fails with a misleading error, and `.env` cannot win.
**Suggested fix**: Call `get_password("api_secret", raise_exception=False)` and treat a missing secret as "differs", so the update path runs.

### 🟡 `ensure_mcp_user` branches have no unit level coverage, `apps/nile_auth/nile_auth/setup.py:79`
**Problem**: The rerun and rotation paths are covered by `test_verify_integration.py`. The refusal after the self check (an existing user with System Manager, or as a Website User), the rollback after insert, and the missing role stop are only in manual verify.md steps. `mcp_user_problems` itself is well tested.
**Why it matters**: These paths are security relevant (never System Manager), and nothing re-runs them automatically.
**Suggested fix**: Add a live script scenario that gives the MCP user System Manager, runs `ensure_mcp_user`, and checks that it exits without changing the key.

### 🟡 `verify deploy` skips the `SCOPES` design and the value validators, `tools/src/nile_tools/verify.py:42`
**Problem**: The spec's value sourcing table says to add a `verify` scope to `config.py` SCOPES. The code uses its own `REQUIRED_KEYS` tuple with a presence check only, so `LMS_HOSTNAME` and the hex32 keys never go through their validators. `LMS_MCP_USER` is required but never used.
**Why it matters**: There are now two lists of required keys to keep in step, and a badly formed hostname or key shows up later as a confusing network FAIL instead of a named config error. AGENTS.md says to validate config at startup.
**Suggested fix**: Add `"verify": ("up",)` (or a narrower `required_for` value) to SCOPES, and run the config check for that scope in `verify_deploy`. Or update the spec to match what was built.

## Nits
- ⚪ `tools/src/nile_tools/verify.py:489`, `load_compose`, `probe` and `mcp_results` are public and used from outside (`cli.py`, the tests), but they are missing from `__all__`.
- ⚪ `tools/src/nile_tools/verify.py:204`, the `MCP_*` constants sit in the middle of the module. Move them up beside the other constants.
- ⚪ `apps/nile_auth/nile_auth/setup.py:104`, this repeats the missing role query from `_mcp_problems`. Compute it once.
- ⚪ `deploy/scripts/restart-test.sh:34`, `.State.Health.Status` aborts with a template error and no `die` message for a service that has no healthcheck. All services have one today. `{{if .State.Health}}...{{else}}none{{end}}` would make it safe if that changes.
- ⚪ The branch is named `feat/course-groups` but its code is spec 0007. Specs 0008 and 0009 are docs only. Say this in the PR description so reviewers do not look for course group code.

## Strengths
- `verify.py` keeps every check a pure function over a response or a parsed compose file. Only `probe` and `run` do I/O, and an injectable `MockTransport` makes the whole command testable offline. The no-secret-in-output test sends the key back in a 403 body, which is a good adversarial check.
- The guard for a matching MCP and service user now runs before any `set-config`, and the uncommitted tests (no bench calls, no site folder) prove it. The integration test also checks that the site setting is unchanged.
- `long_running` is one function shared by the static check and `restart-test`. It finds one shots from `service_completed_successfully`, so new services are classified without a hard coded list.
- `restart-test` is scoped by compose project label, and uses `sudo kill -9` instead of `docker kill` so that `unless-stopped` is really exercised. I checked that `docker compose run` inside `$(...)` gives plain `\n` line endings even from a TTY, so `SERVICES` parses correctly.
- README, `.env.sample`, `deploy/AGENTS.md` and the version pins (0.4.0 in three places) were all updated together.

## Test coverage
482 unit tests pass (`pytest -m "not integration"`). `verify.py` is well covered: every judge, the asset parser limits, network failures, the redirect WARN, the MCP guest, key and SSE cases, and every compose rule with a mutated copy of the real file. `mcp_user_problems`, the create-site ordering and guard, and the config key registration are covered. The gaps: the login refusal of the MCP user has no test at all (Major), the self check and rollback paths of `ensure_mcp_user` run only by hand, and `restart-test.sh` has no automated test (acceptable, since it needs host sudo and is verified live).
