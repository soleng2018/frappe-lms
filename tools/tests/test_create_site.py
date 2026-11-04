"""Unit tests for deploy/scripts/create-site.sh guards, run against a stubbed bench in tmp_path."""

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy/scripts/create-site.sh"
SITE = "lms.example.com"

# The stub logs every call. drop-site fails when FAIL_DROP is set, new-site makes the site folder.
BENCH_STUB = """#!/bin/bash
echo "$*" >> "$BENCH_LOG"
case "$1" in
  drop-site) [ -z "${FAIL_DROP:-}" ] || exit 1 ;;
  new-site) mkdir -p "sites/${@: -1}"; echo '{}' > "sites/${@: -1}/site_config.json" ;;
esac
case "$3" in
  list-apps) printf 'lms\\nnile_auth\\n' ;;
esac
"""


@pytest.fixture
def bench_dir(tmp_path):
    """A fake bench folder with a stub bench on PATH and the script's cd line pointed at it."""
    bench = tmp_path / "bench"
    (bench / "sites").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "bench"
    stub.write_text(BENCH_STUB)
    stub.chmod(0o755)
    script = tmp_path / "create-site.sh"
    script.write_text(SCRIPT.read_text().replace("/home/frappe/frappe-bench", str(bench)))
    return tmp_path


def _run(root: Path, **env: str) -> subprocess.CompletedProcess[str]:
    full_env = {
        "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
        "BENCH_LOG": str(root / "bench.log"),
        "LMS_HOSTNAME": SITE,
        "LMS_ENCRYPTION_KEY": "key",
        "LMS_ADMIN_PASSWORD": "admin",
        "DB_ROOT_PASSWORD": "root",
        "TMPDIR": str(root),
        **env,
    }
    return subprocess.run(
        ["bash", str(root / "create-site.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=full_env,
        timeout=30,
    )


def _calls(root: Path) -> list[str]:
    log = root / "bench.log"
    return log.read_text().splitlines() if log.exists() else []


def test_blank_hostname_fails_before_touching_anything(bench_dir):
    result = _run(bench_dir, LMS_HOSTNAME="")
    assert result.returncode != 0
    assert "LMS_HOSTNAME" in result.stderr
    assert _calls(bench_dir) == []


def test_existing_site_without_config_or_marker_is_never_dropped(bench_dir):
    (bench_dir / "bench/sites" / SITE).mkdir()
    result = _run(bench_dir)
    assert result.returncode == 1
    assert "no site_config.json" in result.stderr
    assert _calls(bench_dir) == []


def test_first_run_creates_site_and_clears_the_pending_marker(bench_dir):
    result = _run(bench_dir)
    assert result.returncode == 0, result.stderr
    sites = bench_dir / "bench/sites"
    assert (sites / SITE / ".created").exists()
    assert not (sites / f".creating-{SITE}").exists()


def test_the_site_users_are_set_up_in_order(bench_dir):
    assert _run(bench_dir, LMS_TIMEZONE="America/Los_Angeles").returncode == 0
    executed = [c for c in _calls(bench_dir) if " execute " in c]
    assert [c.rsplit(" ", 1)[1] for c in executed] == [
        "nile_auth.setup.ensure_service_user",
        "nile_auth.setup.ensure_timezone",
        "nile_auth.setup.ensure_mcp_user",
    ]


def test_the_mcp_user_is_recorded_in_site_config_and_runs_on_a_rerun(bench_dir):
    assert _run(bench_dir, LMS_MCP_USER="nile-mcp@example.com").returncode == 0
    assert any("set-config nile_mcp_user nile-mcp@example.com" in c for c in _calls(bench_dir))
    (bench_dir / "bench.log").unlink()
    assert _run(bench_dir, LMS_MCP_USER="nile-mcp@example.com").returncode == 0
    assert any(c.endswith("ensure_mcp_user") for c in _calls(bench_dir))


def test_interrupted_run_is_dropped_then_recreated(bench_dir):
    sites = bench_dir / "bench/sites"
    (sites / SITE).mkdir()
    (sites / f".creating-{SITE}").touch()
    result = _run(bench_dir)
    assert result.returncode == 0, result.stderr
    calls = _calls(bench_dir)
    assert calls[0].startswith("drop-site")
    assert "--archived-sites-path" in calls[0]
    assert any(c.startswith("new-site") for c in calls)
    assert not (sites / f".creating-{SITE}").exists()


def test_failed_drop_warns_but_still_recovers(bench_dir):
    sites = bench_dir / "bench/sites"
    (sites / SITE).mkdir()
    (sites / f".creating-{SITE}").touch()
    result = _run(bench_dir, FAIL_DROP="1")
    assert result.returncode == 0, result.stderr
    assert "drop-site failed" in result.stderr
    assert (sites / SITE / ".created").exists()


def test_drop_archive_is_deleted(bench_dir):
    sites = bench_dir / "bench/sites"
    (sites / SITE).mkdir()
    (sites / f".creating-{SITE}").touch()
    _run(bench_dir)
    archive = _calls(bench_dir)[0].split("--archived-sites-path ")[1].split()[0]
    assert not Path(archive).exists()


def test_changed_encryption_key_is_refused_without_changes(bench_dir):
    site = bench_dir / "bench/sites" / SITE
    site.mkdir()
    (site / "site_config.json").write_text('{"encryption_key": "stored"}')
    result = _run(bench_dir)
    assert result.returncode == 1
    assert "LMS_ENCRYPTION_KEY differs" in result.stderr
    assert _calls(bench_dir) == []
