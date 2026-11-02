"""Integration tests against the running stack. Run with: pytest -m integration."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
COMPOSE = [
    "docker", "compose", "--project-directory", str(REPO), "-f", str(REPO / "deploy/compose.yaml"),
    "--env-file", str(REPO / "deploy/versions.env"), "--env-file", str(REPO / ".env"),
]


def _compose(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ, "REPO_DIR": str(REPO), "APPS_HASH": "x", **(env or {})}
    return subprocess.run(
        [*COMPOSE, *args], check=False, capture_output=True, text=True, env=full_env, timeout=600
    )


@pytest.fixture(scope="module", autouse=True)
def stack_is_up():
    if shutil.which("docker") is None or not (REPO / ".env").exists():
        pytest.skip("needs docker and a .env")
    ps = _compose("ps", "--status", "running", "--services")
    if "backend" not in ps.stdout.split():
        pytest.skip("the stack is not running (make up)")


def test_create_site_rerun_succeeds_and_keeps_the_site():
    first = _compose("run", "--rm", "--no-deps", "create-site")
    assert first.returncode == 0, first.stderr
    assert "exists" in first.stdout
    second = _compose("run", "--rm", "--no-deps", "create-site")
    assert second.returncode == 0, second.stderr
    assert "Creating site" not in second.stdout


def test_create_site_refuses_a_changed_encryption_key():
    result = _compose(
        "run", "--rm", "--no-deps", "-e", "LMS_ENCRYPTION_KEY=not-the-stored-key", "create-site"
    )
    assert result.returncode == 1
    assert "LMS_ENCRYPTION_KEY differs" in result.stderr


def test_service_user_refuses_a_changed_api_secret():
    result = _compose(
        "run", "--rm", "--no-deps", "-e", "LMS_API_SECRET=not-the-stored-secret", "create-site"
    )
    assert result.returncode != 0
    assert "different API key or secret" in result.stdout + result.stderr
