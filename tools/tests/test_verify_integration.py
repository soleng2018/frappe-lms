"""Integration tests for spec 0007 against the running stack. Run with: pytest -m integration."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from nile_tools import config, verify

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
COMPOSE = [
    "docker",
    "compose",
    "--project-directory",
    str(REPO),
    "-f",
    str(REPO / "deploy/compose.yaml"),
    "--env-file",
    str(REPO / "deploy/versions.env"),
    "--env-file",
    str(REPO / ".env"),
]


def _create_site(*env: str) -> subprocess.CompletedProcess[str]:
    flags = [arg for pair in (("-e", e) for e in env) for arg in pair]
    full_env = {**os.environ, "REPO_DIR": str(REPO), "APPS_HASH": "x"}
    return subprocess.run(
        [*COMPOSE, "run", "--rm", "--no-deps", *flags, "create-site"],
        check=False,
        capture_output=True,
        text=True,
        env=full_env,
        timeout=600,
    )


@pytest.fixture(scope="module")
def values() -> dict[str, str]:
    if shutil.which("docker") is None or not (REPO / ".env").exists():
        pytest.skip("needs docker and a .env")
    return dict(config.load_env(REPO).values)


def test_verify_deploy_has_no_fail_against_the_live_site(values, capsys):
    """AC-1, AC-2, AC-4, AC-7, AC-8: every check except the Cloudflare WARN passes."""
    code = verify.run(REPO, values)
    out = capsys.readouterr().out
    assert code == 0, out
    assert not [ln for ln in out.splitlines() if ln.startswith("FAIL")]
    for secret in (values["LMS_MCP_API_KEY"], values["LMS_MCP_API_SECRET"]):
        assert secret not in out


def test_mcp_user_rerun_changes_nothing_and_rotation_follows_env(values):
    """AC-5: the same values change nothing; a new key is applied; the old one is restored."""
    again = _create_site()
    assert again.returncode == 0, again.stderr
    assert "already set up" in again.stdout
    new_key = "0" * 32
    try:
        rotated = _create_site(f"LMS_MCP_API_KEY={new_key}")
        assert rotated.returncode == 0, rotated.stderr
        assert "key and secret updated" in rotated.stdout
        assert verify.run(REPO, values, say=lambda _: None) == 1  # the old key no longer works
    finally:
        restored = _create_site()
        assert restored.returncode == 0, restored.stderr
    assert verify.run(REPO, values, say=lambda _: None) == 0


def _site_setting(values: dict[str, str], key: str) -> str:
    site = values["LMS_HOSTNAME"]
    out = subprocess.run(
        [*COMPOSE, "exec", "-T", "backend", "bench", "--site", site, "show-config"],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "REPO_DIR": str(REPO), "APPS_HASH": "x"},
        timeout=120,
    ).stdout
    row = next(ln for ln in out.splitlines() if ln.startswith(f"| {key} "))
    return row.split("|")[2].strip()


def test_mcp_user_must_differ_from_the_service_user(values):
    """AC-5: the refusal comes before any write, so the protected user setting is untouched."""
    before = _site_setting(values, "nile_mcp_user")
    result = _create_site(f"LMS_MCP_USER={values['LMS_SERVICE_USER']}")
    assert result.returncode != 0
    assert "must differ" in result.stderr + result.stdout
    assert _site_setting(values, "nile_mcp_user") == before == values["LMS_MCP_USER"]
