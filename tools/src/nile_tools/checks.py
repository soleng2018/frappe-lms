"""Checks on the config file itself: mode, owner, git tracking, leaked secrets, sample drift."""

import os
import stat
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from nile_tools import config

__all__ = ["CheckResult", "GitRunner", "check", "run_git"]

# Runs `git <args>` in the repo with optional stdin; returns (exit code, stdout, first stderr line).
GitRunner = Callable[[list[str], str], tuple[int, str, str]]

_MIN_SCANNED = 16  # shorter secret values would match too much ordinary text


@dataclass(frozen=True)
class CheckResult:
    """Problems fail the check; notes are reminders and skipped steps."""

    problems: tuple[str, ...]
    notes: tuple[str, ...]


def run_git(root: Path) -> GitRunner:
    """Return a runner that executes git inside root."""

    def run(args: list[str], stdin: str) -> tuple[int, str, str]:
        try:
            done = subprocess.run(
                ["git", *args],
                check=False,
                cwd=root,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as e:
            return 127, "", type(e).__name__
        lines = done.stderr.strip().splitlines()
        return done.returncode, done.stdout, lines[0] if lines else ""

    return run


def _file_problems(path: Path) -> list[str]:
    st = path.stat()
    problems = []
    if stat.S_IMODE(st.st_mode) & ~0o600:
        problems.append(f"{path.name} mode is {oct(stat.S_IMODE(st.st_mode))}, run: chmod 600")
    if st.st_uid != os.getuid():
        problems.append(f"{path.name} is not owned by the user running the tools")
    return problems


def _git_problems(secret_values: list[str], git: GitRunner) -> tuple[list[str], list[str]]:
    code, _, err = git(["rev-parse", "--is-inside-work-tree"], "")
    if code != 0:
        return [], [f"git checks skipped: git cannot run here ({err or 'not a repository'})"]
    problems = []
    _, tracked, _ = git(["ls-files", "--", ".env"], "")
    if tracked.strip():
        problems.append(
            ".env is tracked by git: run git rm --cached .env and treat its secrets as exposed"
        )
    patterns = sorted({v for v in secret_values if len(v) >= _MIN_SCANNED})
    hits: set[str] = set()
    for extra in ([], ["--cached"]):
        # Patterns go in on stdin so no secret appears in a process list.
        code, out, err = git(["grep", "-I", "-n", "-F", "-f", "-", *extra], "\n".join(patterns))
        if code > 1:
            return problems, [f"secret scan skipped: git grep failed ({err})"]
        hits |= {":".join(line.split(":", 2)[:2]) for line in out.splitlines() if line}
    problems += [f"a current secret value from .env is in tracked file {h}" for h in sorted(hits)]
    return problems, []


def check(root: Path, scope: str, environ: Mapping[str, str] | None, git: GitRunner) -> CheckResult:
    """Run every config check and return all problems at once, with no secret value in them."""
    problems: list[str] = []
    notes: list[str] = []
    env_path = root / ".env"
    if not env_path.exists():
        return CheckResult((".env does not exist: run make init",), ())
    parsed = config.parse_env(env_path.read_text(), [k.name for k in config.env_keys()])
    problems += parsed.errors
    if parsed.errors:
        # Still name every missing or invalid key, so one syntax error does not hide the rest.
        problems += config.check_values(parsed, config.env_keys(), scope)
    else:
        merged = config.load_env(root, environ)
        problems += config.check_values(merged, config.env_keys(), scope)
        secret_values = [merged.values.get(k.name, "") for k in config.KEYS if k.secret]
        git_problems, git_notes = _git_problems([v for v in secret_values if v], git)
        problems += git_problems
        notes += git_notes
    problems += _file_problems(env_path)
    try:
        versions = config.load_versions(root)
        missing = [k.name for k in config.committed_keys() if not versions.values.get(k.name)]
        problems += [f"deploy/versions.env is missing {name}" for name in missing]
    except (OSError, config.ConfigError) as e:
        problems.append(str(e))
    sample = root / ".env.sample"
    if not sample.exists() or sample.read_text() != config.render_sample():
        problems.append(".env.sample differs from the key list: regenerate with config sample")
    frozen = ", ".join(k.name for k in config.KEYS if k.frozen)
    notes.append(f"Fixed after the first start, never edit: {frozen}")
    return CheckResult(tuple(problems), tuple(notes))
