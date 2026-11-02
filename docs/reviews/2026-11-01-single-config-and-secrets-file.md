# Review, feat/single-config-and-secrets-file (merged to main), 2026-11-01

**Reviewed by**: claude-opus-5-5 (author on a different model session)
**Scope**: 17 files, branch vs main (merge base 7be9313)
**Verdict**: Approve with nits

## Summary
The change adds a key list in `tools/src/nile_tools/config.py` that drives the generated `.env.sample`, a strict dotenv parser with line numbered errors, validators, generators, masking, and a `config check` (`checks.py`) covering syntax, required keys per scope, mode, owner, git tracking, a tracked file secret scan, versions pins and sample drift. The Makefile gains a shell export guard and `up -> build -> check` ordering. It meets AC-1 to AC-9 as specified, and the tests are thorough and assert behaviour, not mocks. The issues left are robustness gaps: a few expected failures surface as raw tracebacks, and one syntax error silently hides the git checks.

## Minor

### 🟡 Expected file errors crash with a traceback instead of a clear message, `tools/src/nile_tools/checks.py:89`, `tools/src/nile_tools/cli.py:61`, `tools/src/nile_tools/cli.py:77`
**Problem**: `main` only catches `ConfigError`. `config show` and `whoami` on a clean clone (no `.env`) raise `FileNotFoundError`. `config check` on a `.env` the tools user cannot read (for example created by root with 0600) raises `PermissionError` at `env_path.read_text()`, before `_file_problems` can report the owner problem. Both confirmed by running the CLI.
**Why it matters**: AGENTS.md asks that expected failures give one consistent error with a clear message. The unreadable case is exactly the situation the owner check exists for, and the operator gets a stack trace instead of "not owned by the user running the tools". The masked excepthook keeps secrets out, so this is not a leak.
**Suggested fix**: In `check`, stat the file first and report mode and owner problems, then catch `OSError` on read and return it as a problem. In `config_show`/`whoami` (or `load_env`), turn a missing or unreadable `.env` into a `ConfigError` that says "run make init" or names the permission issue. Add one test per case.

### 🟡 A syntax error silently skips the tracked `.env` and secret scan, `tools/src/nile_tools/checks.py:91-100`
**Problem**: When `.env` has any syntax error, `_git_problems` is not called, so a tracked `.env` or a pasted secret is not reported in that run, and no note says the scan was skipped. The test `test_a_syntax_error_skips_the_git_scan_but_still_checks_the_file_mode` makes this intended, but the operator is not told.
**Why it matters**: The run still fails, so nothing ships, but "name every problem at once" is not met: the operator fixes the quote, reruns, and only then learns the file is committed. The `git ls-files -- .env` check needs no values and could always run.
**Suggested fix**: Always run the tracked file check. Run the secret scan over the values that did parse, or add a note such as "secret scan skipped until the syntax errors above are fixed".

### 🟡 `--quiet-build` needs a recent Compose, and the README states no minimum version, `Makefile:8`
**Problem**: `TOOLS_RUN` uses `docker compose run --build --quiet-build`. `--quiet-build` is only in recent Compose v2 releases (present in v2.39.4 here). On an older plugin every `make init`, `make check` and `make up` fails with "unknown flag".
**Why it matters**: The first command a new operator runs fails with a message that does not point at the cause.
**Suggested fix**: State the minimum Docker Compose version in the README prerequisites table, or drop `--quiet-build`.

## Nits
- ⚪ `.dockerignore:2-3`, `.env` and `.env.tmp` come before `*` and `!apps/nile_auth`, so they add nothing (the `*` already excludes them) and do not cover `apps/nile_auth/.env`. Put `**/.env` and `**/.env.tmp` after the `!` lines. `test_dockerignore_files_keep_env_out_of_every_build_context` only checks that the lines are present, not their effect.
- ⚪ `tools/src/nile_tools/checks.py:70-76`, with no secret of 16 or more characters the pattern list is empty, `git grep -f -` exits 128 ("no pattern given"), and the note says the scan "failed". Return early with no note when `patterns` is empty.
- ⚪ `tools/src/nile_tools/config.py:507-522`, `install_masking` wraps the current record factory on every call, so tests that call `main` repeatedly stack wrappers. Calling `record.getMessage()` at creation also moves a bad format string error from the handler (where logging swallows it) into the caller.
- ⚪ `tools/src/nile_tools/config.py:452,467`, `add_missing` normalizes trailing blank lines and a missing final newline, so the first `init` on such a file reports "Updated" and rewrites it with no key change. It is stable after that.
- ⚪ `tools/src/nile_tools/config.py:400`, when a value comes from the process environment, the problem still cites the file's line number for that key.
- ⚪ `tools/Dockerfile:6-12`, `git` from apt is unpinned and `safe.directory=*` is broad. Both are acceptable on a one operator dev server, but a comment on why `*` is safe here (a single mounted repo) would help.
- ⚪ `apps/nile_auth/nile_auth/setup.py`, the file uses spaces where AGENTS.md says tabs for `apps/nile_auth/`. This was already true before the change and belongs to spec 0003's formatter.

## Strengths
- One key list really does drive everything: the sample is generated and compared byte for byte, and `test_deploy.py` checks every `${KEY}` in compose, every service's delivered environment, secret placement outside `environment`, and build args against the key list. Drift cannot creep in quietly.
- Careful secret handling throughout: git grep patterns go in on stdin (not argv), hits are cut to `file:line`, parser errors never echo a value, the excepthook and log factory scrub, and `test_no_problem_or_note_ever_contains_a_secret_value` plus the subprocess traceback test prove it.
- `ensure_service_user` exits with a clear message instead of letting `bench execute` hide it behind a `NameError`. The comment records why.
- `init` is truly idempotent (no rewrite when nothing changed), uses an O_EXCL 0600 temp file plus rename, and appends new keys under their group heading.

## Test coverage
Strong. Unit tests cover every parser rejection rule with line numbers, validators, generators, sample generation, `add_missing`/`fill_generated` edges, masking, every `check` branch (mode, owner, tracked file, working tree and index scans, short values, git missing or failing, process environment supply, scopes, versions and sample drift), CLI dispatch and exit codes, and the Makefile guard. Integration tests (marked) cover Compose versus tools parsing parity, `docker inspect` delivery, and image grep for AC-6 and AC-8. Gaps: no test for a missing `.env` on `config show`/`whoami`, or an unreadable `.env` on `config check` (both crash today). The `ensure_service_user` `sys.exit` path is covered only by the stack integration test.
