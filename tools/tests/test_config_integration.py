"""Integration tests for the config file against real Docker. Run with: pytest -m integration."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from nile_tools import config

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
VERSIONS = str(REPO / "deploy/versions.env")
SPECIAL = "a_b.c:d/e@f+g=h,i-j"  # every punctuation character the strict syntax allows
MIN_SECRET = 16


def _compose(env_file: Path, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [
        "docker", "compose", "--project-directory", str(REPO),
        "-f", str(REPO / "deploy/compose.yaml"),
        "--env-file", VERSIONS, "--env-file", str(env_file), *args,
    ]  # fmt: skip
    env = {**os.environ, "REPO_DIR": str(REPO), "APPS_HASH": "x"}
    for key in config.KEYS:
        env.pop(key.name, None)
    return subprocess.run(cmd, check=False, capture_output=True, text=True, env=env, timeout=600)


@pytest.fixture(scope="module", autouse=True)
def needs_docker():
    if shutil.which("docker") is None:
        pytest.skip("needs docker")


def test_compose_and_tools_read_every_accepted_value_the_same_way(tmp_path):
    # covers: AC-5
    env_file = tmp_path / ".env"
    # Hostnames must stay valid hostnames (Compose parses extra_hosts); all else gets SPECIAL.
    value = {
        k.name: "a-b.example.com" if k.validator == "hostname" else SPECIAL for k in config.KEYS
    }
    env_file.write_text("".join(f"{k.name}={value[k.name]}\n" for k in config.env_keys()))
    ours = config.load_env(tmp_path, {}).values
    shown = _compose(env_file, "config", "--format", "json")
    assert shown.returncode == 0, shown.stderr
    services = json.loads(shown.stdout)["services"]
    checked = 0
    for service, mapping in config.delivery().items():
        for var, key in mapping.items():
            assert services[service]["environment"][var] == ours[key] == value[key], (service, var)
            checked += 1
    assert checked == sum(len(m) for m in config.delivery().values())


def test_compose_expands_a_dollar_sign_so_the_strict_syntax_must_reject_it(tmp_path):
    # covers: AC-5
    env_file = tmp_path / ".env"
    env_file.write_text("LMS_HOSTNAME=a$HOME\n")
    assert config.parse_env(env_file.read_text(), ["LMS_HOSTNAME"]).errors
    shown = _compose(env_file, "config", "--format", "json")
    value = json.loads(shown.stdout)["services"]["frontend"]["environment"]
    assert value["FRAPPE_SITE_NAME_HEADER"] != "a$HOME"


def _secrets() -> dict[str, str]:
    values = config.load_env(REPO, {}).values
    return {
        k.name: values[k.name]
        for k in config.KEYS
        if k.secret and len(values.get(k.name, "")) >= MIN_SECRET
    }


@pytest.fixture(scope="module")
def live_env():
    if not (REPO / ".env").exists():
        pytest.skip("needs a .env")
    return REPO / ".env"


def _inspect(ids: list[str]) -> list[dict]:
    done = subprocess.run(
        ["docker", "inspect", *ids], check=True, capture_output=True, text=True, timeout=60
    )
    return json.loads(done.stdout)


def test_each_container_holds_only_the_secrets_its_delivery_row_lists(live_env):
    # covers: AC-6
    ps = _compose(live_env, "ps", "-a", "-q")
    ids = ps.stdout.split()
    if not ids:
        pytest.skip("the stack has no containers (make up)")
    secrets = _secrets()
    delivery = config.delivery()
    for box in _inspect(ids):
        service = box["Config"]["Labels"]["com.docker.compose.service"]
        env = dict(item.partition("=")[::2] for item in box["Config"]["Env"])
        holding = {
            var: key for var, value in env.items() for key, s in secrets.items() if s == value
        }
        expected = {var: key for var, key in delivery.get(service, {}).items() if key in secrets}
        assert holding == expected, service
        box["Config"].pop("Env")
        rest = json.dumps(box)
        for key, value in secrets.items():
            assert value not in rest, f"{key} outside the environment of {service}"


def test_the_tools_container_holds_no_secret_in_its_environment(live_env):
    # covers: AC-6
    made = _compose(live_env, "create", "tools")
    assert made.returncode == 0, made.stderr
    try:
        ids = _compose(live_env, "ps", "-a", "-q", "tools").stdout.split()
        assert ids
        text = json.dumps(_inspect(ids))
        for key, value in _secrets().items():
            assert value not in text, key
    finally:
        _compose(live_env, "rm", "-f", "tools")


def _stream_contains(image: str, needles: dict[str, str]) -> set[str]:
    """Names of needles found anywhere in `docker save image`, read in chunks."""
    keep = max(len(v) for v in needles.values()) - 1
    found: set[str] = set()
    proc = subprocess.Popen(["docker", "save", image], stdout=subprocess.PIPE)
    assert proc.stdout is not None
    tail = b""
    while chunk := proc.stdout.read(1 << 20):
        window = tail + chunk
        found |= {k for k, v in needles.items() if v.encode() in window}
        tail = window[-keep:]
    proc.wait()
    return found


def test_the_tools_image_contains_no_value_from_env(live_env):
    # covers: AC-8
    needles = _secrets()
    assert needles
    assert _stream_contains("nile-tools:local", needles) == set()


def test_the_lms_image_history_and_metadata_carry_no_value_from_env(live_env):
    # covers: AC-8
    images = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}", "nile-lms"],
        check=True, capture_output=True, text=True,
    ).stdout.split()  # fmt: skip
    if not images:
        pytest.skip("the LMS image is not built")
    for image in images:
        history = subprocess.run(
            ["docker", "history", "--no-trunc", "--format", "{{.CreatedBy}}", image],
            check=True, capture_output=True, text=True,
        ).stdout  # fmt: skip
        meta = json.dumps(_inspect([image]))
        for key, value in _secrets().items():
            assert value not in history + meta, (image, key)
