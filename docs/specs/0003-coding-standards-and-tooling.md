# 0003. One set of coding standards, enforced by one lint command and a commit hook

**Date**: 2026-11-01
**Status**: Accepted

## Summary

Every file type in this repo gets one agreed style and one automatic check: Ruff and mypy for Python, shellcheck and shfmt for shell, hadolint and `docker compose config` for Docker files, and gitleaks for secrets. The same checks run from `make lint` and from a git pre-commit hook, so a bad commit is stopped on the dev server before it lands. The custom Frappe app `nile_auth` follows Frappe's own style (tabs, 110 columns), while our own `tools` package uses spaces and a stricter rule set. Nothing is installed by this spec; the scaffold feature builds it from the definition below.

## Context

The repo holds only docs, brand assets, and two specs. There is no code yet, so there are no competing patterns to untangle. The cost of agreeing now is zero, and the cost of agreeing later is a reformatting commit across every file.

Spec 0001 already picked `uv`, `pytest`, and `ruff` for Python and left the final lint choices to this feature. Spec 0002 added a root `Makefile` whose `check` target means "check the config file", so new targets must not reuse that name. There is a GitHub remote (`soleng2018/frappe-lms`) but no CI, and the work happens on one dev server with Docker and `uv`.

The repo mixes four kinds of code with different norms: Python scripts we own (`tools/`), a Frappe app that must look like Frappe code (`apps/nile_auth/`), shell and Dockerfiles for the image, and a compose file plus YAML. A secret pasted into any of them is the worst failure, since the Authentik master token lives next to this code.

## Options considered

### Option 1: Document the standard and enforce it from the first line of code

One lint command and a commit hook run the same checks. No file lands unformatted, because there are no old files to migrate.

**Pros**:
- Strongest enforcement that needs no hosted service.
- No rollout debt, since no code exists yet.
- `make lint` and the hook cannot drift, because they run the same config. (`make lint` adds one full tree secret scan.)

**Cons**:
- A hook can be skipped with `git commit --no-verify`, and nothing else catches it.
- Needs `uv`, `pre-commit`, and Docker on every machine that commits.

### Option 2: Option 1 plus GitHub Actions CI

The same checks also run on every push.

**Pros**:
- Catches skipped hooks.
- Gives a visible pass or fail on the remote.

**Cons**:
- One more thing to build, secure, and keep green, with no team yet to protect from each other.
- The hosted runner has none of the Docker and Traefik setup, so only lint could run there.

### Option 3: Document only, rely on review

**Pros**:
- No tooling at all.

**Cons**:
- Review is the weakest enforcement, and an AI agent writes much of this code. Style drift and a leaked token would be found late or never.

## Decision

**Chosen option**: Option 1: document and enforce from the first line of code.

Use the standard below, enforced by `make lint` and a pre-commit hook that run the same `.pre-commit-config.yaml`. CI is deferred.

**Implementation skills**: `uv` (`astral-sh/claude-code-plugins`, `.claude/skills/uv/`) · `docker-compose-patterns` (`docker/skills`, `.claude/skills/docker-compose-patterns/`)

## Rationale

Spec 0001 and 0002 need a check that runs on one dev server with no hosted pieces, and the repo has no code to migrate, so the cheapest strong option is a hook plus a `make` target (basis: the Context above). CI protects against teammates who skip hooks, and there is one author and agent writing here today. The remote exists, so adding CI later is a small step (Option 2 stays open as a Follow-up).

Tool picks, each with the runner up: Ruff for lint and format because it replaces flake8, isort, and black with one fast tool already named in 0001 (runner up: Black plus flake8). mypy in standard mode because it is the mature default and the package is small (runner up: pyright; `ty` is newer and its rules may still move). The balanced Ruff rule set catches real bugs (B), unsafe calls (S), and old syntax (UP) without the churn of enabling every rule. `nile_auth` follows Frappe's style because the app is read next to framework code, `bench` templates generate that style, and fighting it adds noise to every Frappe example the team copies.

Hooks run through `pre-commit` so each tool is pinned and shared by clone. Ruff and mypy are the exception: they run as local hooks through `uv`, so their versions come from `tools/uv.lock` and cannot drift from what the tests use.

## Standard definition

**Scope and layout** (the scaffold feature creates these; names not fixed here are its call):

| Path | Holds | Style |
|---|---|---|
| `tools/` | Python package, `src` layout: `tools/src/<package>/`, `tools/tests/`, `tools/pyproject.toml`, `tools/uv.lock` | Spaces, 100 columns |
| `apps/nile_auth/` | Custom Frappe app, with its own `[tool.ruff]` in its `pyproject.toml` | Frappe style: tabs, 110 columns |
| `deploy/scripts/*.py`, `deploy/pyproject.toml` | Stdlib only container scripts (healthchecks) and their Ruff config | Spaces, 100 columns |
| `deploy/`, `Makefile`, shell scripts | Compose, Dockerfiles, wrapper | See table below |
| `brand/`, `.claude/`, `.agents/`, `skills-lock.json`, `uv.lock` | Third party or generated files | Excluded from every hook, never reformatted |

The only Python outside `tools/` and `apps/nile_auth/` is the small stdlib scripts the containers run, in `deploy/scripts/`. They get a third, minimal config in `deploy/pyproject.toml` (not a package), so every Python file still finds a project config. Without one, Ruff silently falls back to its 88 column default. A test in `tools/tests/test_standards.py` fails if any Python file has no `pyproject.toml` above it. Dockerfiles in this repo are ours and are linted. If the layered frappe_docker Containerfile is ever copied in unchanged, keep it in its own folder and add that folder to the hook `exclude`.

**Rules by file type**:

| File type | Tool | Rule |
|---|---|---|
| Python in `tools/` | `ruff check` and `ruff format` | Line length 100, spaces, double quotes, target Python 3.12. `select` = `E, W, F, I, B, UP, SIM, C4, S, RUF, ANN, D100, D101, D102, D103`. Tests ignore `S101`, `ANN`, and `D`. Docstring style Google, one summary line is enough. Calls that run `git` with a fixed argument list (spec 0002's scan) carry a line level `# noqa: S603, S607` with a reason. `ANN401` is ignored project wide so `Any` is allowed where a library demands it. |
| Python in `tools/` | `mypy` | Standard mode, `python_version = "3.12"`, `check_untyped_defs`, `warn_unused_ignores`, `warn_redundant_casts`, checks `src` and `tests`. Ruff's `ANN` rules, not mypy, enforce that every signature has parameter and return hints. |
| Python in `deploy/scripts/` | `ruff check` and `ruff format` | Line length 100, spaces, target Python 3.12. `select` = `E, W, F, I, B, UP, SIM, C4, RUF`. No mypy, no `ANN`, `D` or `S`: these are short stdlib scripts that run inside the Frappe image, not the typed `tools` package. |
| Python in `apps/nile_auth/` | `ruff check` and `ruff format` | Copy the lint settings from the Frappe `version-16` app template (`bench new-app`): tabs, line length 110, target version from the Python in the Frappe image. Verify the template's current values at build time. No mypy, no `ANN`, no `D` here. |
| Shell | `shellcheck` and `shfmt -i 2 -ci` | Logic beyond a few lines belongs in Python, not shell. |
| Dockerfiles | `hadolint` | Default rules. Each ignore needs a comment saying why. |
| Compose | `make compose-config` | Uses spec 0002's command prefix (`--project-directory .`, `--env-file deploy/versions.env --env-file .env.sample`) plus `--profile tools config -q`, so the pinned versions resolve and the `tools` service is included. Must pass on a clean clone using only committed files. No YAML style linter. |
| Any text file | `pre-commit-hooks`: `end-of-file-fixer`, `trailing-whitespace`, `check-merge-conflict`, `check-added-large-files`, `detect-private-key` | LF endings, final newline. |
| Any file | `gitleaks` | The hook blocks a secret in staged changes. `make lint` also runs `gitleaks dir .` so the whole tree is covered, because the hook scans only staged changes. Spec 0002's `.env` scan stays and covers the config file. |
| Markdown | None | Docs follow the output style of the skills that write them. |
| Commit messages | Convention only | A plain imperative sentence, short first line, optional body. Not machine checked. |
| Client side JavaScript | Avoid | If `nile_auth` ever needs it, follow Frappe's prettier and eslint setup and amend this spec. |

An `.editorconfig` at the root states the same indentation for editors: tabs for `apps/nile_auth/**/*.py` and `Makefile`, 2 spaces for YAML and shell, 4 spaces for `tools/**/*.py` and `deploy/scripts/*.py`.

**Tests**: `pytest` with `pytest-cov`. Coverage prints with `--cov --cov-report=term-missing` and never fails the run. Tests marked `integration` need a live Frappe or Authentik and are excluded from `make test` (`-m "not integration"`). Unit tests must not touch the network or a real `.env`.

**Commands** (root `Makefile`, added to the wrapper from spec 0002; `make check` keeps meaning "check the config file"):

| Target | Does |
|---|---|
| `make hooks` | `uv run --project tools pre-commit install` (run once per clone) |
| `make lint` | `pre-commit run --all-files`, then `gitleaks dir .`. The hooks fix what they can (Ruff, shfmt, whitespace); pre-commit fails the run when a hook changed a file, so re-run after the fix |
| `make fmt` | Alias of `make lint` (one path, so formatting and import sorting cannot be skipped) |
| `make compose-config` | The compose check from the table above. The compose hook calls it |
| `make test` | `uv run --frozen --directory tools pytest --cov --cov-report=term-missing` |

Dev dependencies (`ruff`, `mypy`, `pytest`, `pytest-cov`, `pre-commit`, type stubs such as `types-PyYAML`) sit in the `dev` dependency group in `tools/pyproject.toml`. uv installs that group by default, so the runtime tools image must use `uv sync --frozen --no-dev`. Hooks and `make` targets use `uv run --frozen`, so a commit can never rewrite `uv.lock`.

The tools project is a real package: `[build-system]` block, `requires-python = ">=3.12,<3.13"`, and a `.python-version` file, so tests import `src/<package>` as installed.

**Canonical pattern** (`tools/pyproject.toml` excerpt and a compliant function):

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "UP", "SIM", "C4", "S", "RUF", "ANN", "D100", "D101", "D102", "D103"]
ignore = ["ANN401"]

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "ANN", "D"]

[tool.mypy]
python_version = "3.12"
files = ["src", "tests"]
check_untyped_defs = true
warn_unused_ignores = true
warn_redundant_casts = true

[tool.pytest.ini_options]
addopts = "-m 'not integration'"
markers = ["integration: needs a live Frappe or Authentik"]

[tool.coverage.run]
source = ["<package>"]
```

```python
def site_url(hostname: str) -> str:
    """Return the public https URL for a site hostname."""
    return f"https://{hostname}"
```

`.pre-commit-config.yaml` (shape only; pin `rev` values to current releases and verify hook ids at build time):

```yaml
exclude: ^(brand/|\.claude/|\.agents/|skills-lock\.json|uv\.lock$)
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks   # the five hygiene hooks above; exclude apps/nile_auth/**/*.json from end-of-file-fixer and trailing-whitespace (Frappe generates those files)
  - repo: https://github.com/shellcheck-py/shellcheck-py   # shellcheck
  - repo: https://github.com/scop/pre-commit-shfmt         # shfmt, args: [-i, "2", -ci, -w] (fixes; pre-commit fails the run when a file changed)
  - repo: https://github.com/hadolint/hadolint             # hadolint-docker hook, needs Docker
  - repo: https://github.com/gitleaks/gitleaks             # gitleaks (staged changes only)
  - repo: local
    hooks:
      # every local hook: language: system, require_serial: true
      - id: ruff-check   # uv run --frozen --project tools ruff check --fix; types: [python]; run from the repo root so the nearest pyproject wins per file
      - id: ruff-format  # uv run --frozen --project tools ruff format; types: [python]
      - id: mypy         # uv run --frozen --directory tools mypy; files: ^tools/; pass_filenames: false
      - id: compose-config  # make compose-config; files: ^(deploy/|\.env\.sample$); pass_filenames: false
```

**Replaces**:
- Per developer editor settings as the only source of style
- Running `black`, `flake8`, or `isort` separately; Ruff covers all three
- Hand checking compose and Dockerfiles at `up` time

**Enforcement**: `.pre-commit-config.yaml` at the repo root (all hooks), `tools/pyproject.toml` and `apps/nile_auth/pyproject.toml` (Ruff, mypy, pytest settings), and `.editorconfig`. `make lint` runs the same config the hook runs.

**Rollout**: New code only, from the first commit of code. There is no old code to migrate. The scaffold feature (scope #1) must leave `make lint` and `make test` clean, which is also this feature's done check in the scope. Bypassing the hook with `--no-verify` is allowed only for an emergency fix and the next commit must pass `make lint`.

**Exceptions**: A single rule may be switched off on a line with `# noqa: <code>` and a reason, or in `per-file-ignores` with a comment. Generated files (lock files) and the excluded paths above are never checked. No other exceptions.

## Consequences

**Positive**:
- One command and one hook cover every file type, with versions pinned by `pre-commit` and `uv.lock`.
- A pasted token or private key is stopped at commit time, not found in history.
- `nile_auth` reads like the Frappe code around it, and `tools` stays strictly typed and documented.
- No rollout cost, since the standards exist before the code.

**Negative / tradeoffs**:
- Two Python styles in one repo (tabs and 110 in `nile_auth`, spaces and 100 in `tools`). A person moving between them must switch.
- Every committer needs `uv`, `pre-commit`, and Docker (for hadolint). A machine without Docker cannot commit Dockerfile changes cleanly.
- `--no-verify` and a missing `make hooks` both bypass the checks, and no CI catches that yet.
- The `ANN` and `D` rules and mypy add friction to quick scripts. They are chosen on purpose for code an agent writes and a human maintains.
- Hook ids and revs are unverified until the scaffold runs them; a renamed hook means a config edit.

**Neutral**:
- `nile_auth` tests are not covered here. Frappe tests need a site, so their command belongs to scope #7.
- The dev dependency group means the runtime tools image carries no linters.
- `gitleaks` may need a small allowlist if sample values trip it.

## Follow-up

- [x] Root `AGENTS.md` does not exist. `/audit` should create it with these commands (`make lint`, `make fmt`, `make test`, `make hooks`), the two Python styles, and the three installed skills from spec 0001. `/audit` and `/sync` own that file.
- [ ] Decide later whether to add GitHub Actions running `make lint` (Option 2). Revisit when a second committer appears or a hook is skipped.
- [ ] Scope #7 (`nile_auth`) defines how its tests run (`bench run-tests` in a container) and whether they join `make test`.
- [ ] Verify at build time: the `version-16` app template's ruff settings, the Python version in the Frappe image, current `pre-commit` hook ids and revs, and that `docker compose config -q` passes with only `.env.sample` (spec 0002 requires the wrapper, not `:?` checks, so it should).
- [ ] Scope #2 lists `/audit` then `/develop tooling` then `/test`. This spec feeds the middle step; the install happens after the scaffold exists.
- [ ] Agent Skills and MCP servers for ruff, mypy, pre-commit, hadolint, shellcheck, and gitleaks were not searched. Offer again if the build feels like guessing at their conventions.
- [ ] Add a place for integration tests to run (tools container, a `make test-int` target) when the first one is written.
- [ ] Once the tools image exists, also run `make test` inside it. Spec 0002 runs the tools under an arbitrary uid, and tests that pass on the host can fail there.
- [ ] Spec 0002's `.env.sample` generator must write a final newline and no trailing spaces, or the whitespace fixers will rewrite it and fight the sample matches key list test.
- [ ] Docker stays a stated requirement for committing (hadolint-docker and the compose check). The `hadolint-py` hook would remove it for Dockerfiles only; revisit if that becomes a nuisance.
