"""Spec 0003: the committed lint, format and hook config says what the spec says it says."""

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".venv", ".git", "brand", ".claude", ".agents", ".upstream", "__pycache__"}


def toml(path: str) -> dict[str, Any]:
    return tomllib.loads((ROOT / path).read_text())


def hooks() -> dict[str, dict[str, Any]]:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    return {hook["id"]: hook for repo in config["repos"] for hook in repo["hooks"]}


def python_files() -> list[Path]:
    return [
        p
        for p in ROOT.rglob("*.py")
        if not SKIP_DIRS & set(p.relative_to(ROOT).parts) and ".venv" not in p.parts
    ]


def nearest_pyproject(path: Path) -> Path | None:
    for parent in path.parents:
        if (parent / "pyproject.toml").exists():
            return parent / "pyproject.toml"
        if parent == ROOT:
            break
    return None


class TestToolsRuff:
    def test_uses_line_length_100_and_python_312(self) -> None:
        ruff = toml("tools/pyproject.toml")["tool"]["ruff"]
        assert ruff["line-length"] == 100
        assert ruff["target-version"] == "py312"

    def test_selects_the_rule_set_from_the_spec(self) -> None:
        lint = toml("tools/pyproject.toml")["tool"]["ruff"]["lint"]
        spec_rules = {"E", "W", "F", "I", "B", "UP", "SIM", "C4", "S", "RUF", "ANN"}
        assert spec_rules | {"D100", "D101", "D102", "D103"} <= set(lint["select"])
        assert lint["ignore"] == ["ANN401"]

    def test_uses_google_docstring_convention(self) -> None:
        lint = toml("tools/pyproject.toml")["tool"]["ruff"]["lint"]
        assert lint["pydocstyle"]["convention"] == "google"

    def test_tests_may_assert_and_skip_hints_and_docstrings(self) -> None:
        ignores = toml("tools/pyproject.toml")["tool"]["ruff"]["lint"]["per-file-ignores"]
        assert {"S101", "ANN", "D"} <= set(ignores["tests/**"])

    def test_source_does_not_ignore_security_or_typing_rules(self) -> None:
        ignores = toml("tools/pyproject.toml")["tool"]["ruff"]["lint"]["per-file-ignores"]
        assert set(ignores) == {"tests/**"}


class TestToolsMypyAndPytest:
    def test_mypy_checks_src_and_tests_with_the_strict_flags(self) -> None:
        mypy = toml("tools/pyproject.toml")["tool"]["mypy"]
        assert mypy["python_version"] == "3.12"
        assert mypy["files"] == ["src", "tests"]
        assert mypy["check_untyped_defs"] is True
        assert mypy["warn_unused_ignores"] is True
        assert mypy["warn_redundant_casts"] is True

    def test_integration_tests_are_excluded_by_default(self) -> None:
        pytest_cfg = toml("tools/pyproject.toml")["tool"]["pytest"]["ini_options"]
        assert "not integration" in pytest_cfg["addopts"]
        assert any(m.startswith("integration:") for m in pytest_cfg["markers"])

    def test_coverage_measures_the_package(self) -> None:
        assert toml("tools/pyproject.toml")["tool"]["coverage"]["run"]["source"] == ["nile_tools"]

    def test_package_is_built_and_pinned_to_python_312(self) -> None:
        project = toml("tools/pyproject.toml")
        assert project["project"]["requires-python"] == ">=3.12,<3.13"
        assert "build-backend" in project["build-system"]
        assert (ROOT / "tools/.python-version").read_text().strip().startswith("3.12")

    def test_dev_group_holds_every_checker(self) -> None:
        dev = toml("tools/pyproject.toml")["dependency-groups"]["dev"]
        names = {re.split(r"[<>=!~ ]", dep, maxsplit=1)[0] for dep in dev}
        assert {"ruff", "mypy", "pytest", "pytest-cov", "pre-commit", "types-PyYAML"} <= names

    def test_runtime_dependencies_exclude_the_checkers(self) -> None:
        deps = toml("tools/pyproject.toml")["project"]["dependencies"]
        assert not [d for d in deps if re.match(r"(ruff|mypy|pytest|pre-commit)", d)]


class TestNileAuthRuff:
    def test_follows_frappe_style_with_tabs_and_110_columns(self) -> None:
        ruff = toml("apps/nile_auth/pyproject.toml")["tool"]["ruff"]
        assert ruff["line-length"] == 110
        assert ruff["format"]["indent-style"] == "tab"

    def test_has_no_mypy_or_docstring_rules(self) -> None:
        project = toml("apps/nile_auth/pyproject.toml")
        selected = set(project["tool"]["ruff"]["lint"]["select"])
        assert "mypy" not in project["tool"]
        assert not {"ANN", "D"} & selected

    def test_tab_indent_warning_is_switched_off(self) -> None:
        assert "W191" in toml("apps/nile_auth/pyproject.toml")["tool"]["ruff"]["lint"]["ignore"]

    def test_source_files_are_indented_with_tabs(self) -> None:
        for path in (ROOT / "apps/nile_auth").rglob("*.py"):
            indented = [ln for ln in path.read_text().splitlines() if ln.startswith(" ")]
            assert not indented, f"{path.relative_to(ROOT)} has space indented lines"


class TestPreCommitConfig:
    def test_runs_every_hook_the_spec_lists(self) -> None:
        expected = {
            "end-of-file-fixer",
            "trailing-whitespace",
            "check-merge-conflict",
            "check-added-large-files",
            "detect-private-key",
            "shellcheck",
            "shfmt",
            "hadolint-docker",
            "gitleaks",
            "ruff-check",
            "ruff-format",
            "mypy",
            "compose-config",
        }
        assert expected <= set(hooks())

    def test_third_party_and_generated_paths_are_excluded(self) -> None:
        config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
        pattern = re.compile(config["exclude"])
        for excluded in ("brand/logo.svg", ".claude/skills/x.md", ".agents/x", "skills-lock.json"):
            assert pattern.match(excluded), excluded
        assert pattern.match("tools/uv.lock")
        assert not pattern.match("tools/src/nile_tools/config.py")
        assert not pattern.match("deploy/compose.yaml")

    def test_frappe_generated_json_skips_the_whitespace_fixers(self) -> None:
        for hook_id in ("end-of-file-fixer", "trailing-whitespace"):
            assert re.match(hooks()[hook_id]["exclude"], "apps/nile_auth/nile_auth/x.json")

    def test_ruff_and_mypy_run_through_frozen_uv(self) -> None:
        for hook_id in ("ruff-check", "ruff-format", "mypy"):
            entry = hooks()[hook_id]["entry"]
            assert entry.startswith("uv run --frozen"), hook_id

    def test_local_hooks_run_one_at_a_time(self) -> None:
        for hook_id in ("ruff-check", "ruff-format", "mypy", "compose-config"):
            assert hooks()[hook_id]["require_serial"] is True, hook_id

    def test_mypy_checks_the_whole_package_not_single_files(self) -> None:
        mypy = hooks()["mypy"]
        assert mypy["pass_filenames"] is False
        assert re.match(mypy["files"], "tools/src/nile_tools/cli.py")
        assert not re.match(mypy["files"], "apps/nile_auth/nile_auth/setup.py")

    def test_compose_check_runs_for_deploy_and_sample_changes_only(self) -> None:
        pattern = hooks()["compose-config"]["files"]
        assert re.match(pattern, "deploy/compose.yaml")
        assert re.match(pattern, ".env.sample")
        assert not re.match(pattern, "tools/src/nile_tools/config.py")

    def test_hook_repos_are_pinned_to_a_release(self) -> None:
        config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
        for repo in config["repos"]:
            if repo["repo"] != "local":
                assert re.match(r"v\d", repo["rev"]), repo["repo"]

    def test_shfmt_uses_two_space_indent_and_indented_case(self) -> None:
        assert hooks()["shfmt"]["args"] == ["-i", "2", "-ci", "-w"]


class TestEditorConfig:
    def sections(self) -> dict[str, dict[str, str]]:
        found: dict[str, dict[str, str]] = {}
        current = ""
        for line in (ROOT / ".editorconfig").read_text().splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                current = line[1:-1]
                found[current] = {}
            elif "=" in line and current:
                key, value = (part.strip() for part in line.split("=", 1))
                found[current][key] = value
        return found

    def test_default_is_lf_utf8_two_spaces_with_final_newline(self) -> None:
        star = self.sections()["*"]
        assert star["end_of_line"] == "lf"
        assert star["charset"] == "utf-8"
        assert star["insert_final_newline"] == "true"
        assert (star["indent_style"], star["indent_size"]) == ("space", "2")

    def test_nile_auth_and_makefile_use_tabs(self) -> None:
        sections = self.sections()
        assert sections["apps/nile_auth/**.py"]["indent_style"] == "tab"
        assert sections["Makefile"]["indent_style"] == "tab"

    def test_tools_python_uses_four_spaces(self) -> None:
        assert self.sections()["tools/**.py"]["indent_size"] == "4"

    def test_deploy_scripts_use_four_spaces(self) -> None:
        assert self.sections()["deploy/scripts/**.py"]["indent_size"] == "4"

    def test_markdown_keeps_trailing_spaces(self) -> None:
        assert self.sections()["*.md"]["trim_trailing_whitespace"] == "false"


class TestMakefileTargets:
    def makefile(self) -> str:
        return (ROOT / "Makefile").read_text()

    @pytest.mark.parametrize(
        "target", ["hooks", "lint", "fmt", "test", "compose-config", "secrets", "check"]
    )
    def test_target_is_defined_and_phony(self, target: str) -> None:
        text = self.makefile()
        assert re.search(rf"^{re.escape(target)}:", text, re.MULTILINE)
        phony = re.search(r"^\.PHONY:(.*)$", text, re.MULTILINE)
        assert phony and target in phony.group(1).split()

    def test_check_still_means_the_config_file_check(self) -> None:
        assert "config check --for up" in self.makefile()

    def test_fmt_is_an_alias_of_lint(self) -> None:
        assert re.search(r"^fmt: lint$", self.makefile(), re.MULTILINE)

    def test_lint_scans_for_secrets_before_the_hooks(self) -> None:
        assert re.search(r"^lint: secrets$", self.makefile(), re.MULTILINE)

    def test_test_target_prints_missing_lines_and_uses_frozen_lock(self) -> None:
        text = self.makefile()
        assert "uv run --frozen --directory tools pytest --cov --cov-report=term-missing" in text

    def test_gitleaks_image_is_pinned_by_digest(self) -> None:
        assert re.search(r"^GITLEAKS_IMAGE = \S+@sha256:[0-9a-f]{64}$", self.makefile(), re.M)

    def test_compose_config_uses_the_sample_file_not_a_real_env(self) -> None:
        line = next(ln for ln in self.makefile().splitlines() if "--profile tools config -q" in ln)
        assert "--env-file .env.sample" in line
        assert "--env-file .env " not in line


class TestSecretScanConfig:
    def test_default_rules_stay_on(self) -> None:
        text = (ROOT / ".gitleaks.toml").read_text()
        assert tomllib.loads(text)["extend"]["useDefault"] is True

    def test_real_env_file_is_skipped_by_the_tree_scan(self) -> None:
        paths = tomllib.loads((ROOT / ".gitleaks.toml").read_text())["allowlist"]["paths"]
        assert any(re.search(p, ".env") for p in paths)
        assert any(re.search(p, "deploy/.env") for p in paths)

    def test_application_code_is_not_allowlisted(self) -> None:
        paths = tomllib.loads((ROOT / ".gitleaks.toml").read_text())["allowlist"]["paths"]
        for source in ("tools/src/nile_tools/config.py", ".env.sample", "deploy/compose.yaml"):
            assert not any(re.search(p, source) for p in paths), source

    def test_real_env_file_is_ignored_by_git(self) -> None:
        lines = (ROOT / ".gitignore").read_text().splitlines()
        assert ".env" in (line.strip() for line in lines)


class TestEveryPythonFileHasAConfig:
    def test_no_python_file_falls_outside_the_two_configured_projects(self) -> None:
        # Spec 0003: "No Python lives outside tools/ and apps/nile_auth/", so ruff always finds
        # a project config. Without one, ruff silently falls back to its 88 column default.
        orphans = [str(p.relative_to(ROOT)) for p in python_files() if nearest_pyproject(p) is None]
        assert orphans == []
