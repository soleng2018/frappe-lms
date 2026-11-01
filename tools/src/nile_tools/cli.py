"""Commands: init (create .env with generated secrets), whoami (prove the API path works)."""

import argparse
import base64
import os
import secrets
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType

import httpx

__all__ = ["GENERATED", "ConfigError", "init", "main", "read_env", "whoami"]

# Keys the operator must fill in by hand; init lists the blank ones.
REQUIRED_OPERATOR_KEYS = ("LMS_HOSTNAME", "AUTHENTIK_HOSTNAME", "AUTHENTIK_API_TOKEN")


class ConfigError(Exception):
    """A required config key is missing or blank; the message names the key."""


def _password() -> str:
    while True:
        value = secrets.token_urlsafe(24)
        if value[0].isalnum():
            return value


GENERATED: Mapping[str, Callable[[], str]] = MappingProxyType(
    {
        "LMS_ADMIN_PASSWORD": _password,
        "DB_ROOT_PASSWORD": _password,
        "LMS_ENCRYPTION_KEY": lambda: base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "LMS_API_KEY": lambda: secrets.token_hex(16),
        "LMS_API_SECRET": lambda: secrets.token_hex(16),
    }
)


def read_env(path: Path) -> dict[str, str]:
    """Read KEY=value lines from a dotenv file, process environment winning for known keys."""
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key] = value
    return {**values, **{k: v for k, v in os.environ.items() if k in values}}


def _write_private(path: Path, text: str) -> None:
    path.unlink(missing_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def init(root: Path) -> int:
    """Create .env from the sample, fill blank generated secrets, report blank operator keys."""
    env, sample = root / ".env", root / ".env.sample"
    if not env.exists():
        _write_private(env, sample.read_text())
    lines, changed = [], False
    for line in env.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key in GENERATED and not value:
            line, changed = f"{key}={GENERATED[key]()}", True
        lines.append(line)
    if changed:
        tmp = root / ".env.tmp"
        _write_private(tmp, "\n".join(lines) + "\n")
        tmp.replace(env)
    values = read_env(env)
    print(f"{'Updated' if changed else 'Kept'} {env}")
    blank = [key for key in REQUIRED_OPERATOR_KEYS if not values.get(key)]
    if blank:
        print(f"Still blank, fill these in: {', '.join(blank)}")
    return 0


def _require(values: Mapping[str, str], key: str) -> str:
    if not values.get(key):
        raise ConfigError(f"Config key {key} is missing or blank in .env")
    return values[key]


def whoami(root: Path) -> int:
    """Call the LMS API as the service user, retrying for 5 minutes, and print its name."""
    values = read_env(root / ".env")
    host, key, secret = (_require(values, k) for k in ("LMS_HOSTNAME", "LMS_API_KEY", "LMS_API_SECRET"))
    url = f"https://{host}/api/method/frappe.auth.get_logged_user"
    headers = {"Authorization": f"token {key}:{secret}"}
    deadline = time.monotonic() + 300
    last = ""
    while True:
        try:
            r = httpx.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                print(r.json()["message"])
                return 0
            last = f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            last = type(e).__name__
        if time.monotonic() >= deadline:
            print(f"Could not reach {url} after 5 minutes (last error: {last})", file=sys.stderr)
            return 1
        time.sleep(5)


def main() -> int:
    """Run the named command; a ConfigError prints its message and exits 1."""
    parser = argparse.ArgumentParser(prog="tools")
    parser.add_argument("command", choices=["init", "whoami"])
    args = parser.parse_args()
    try:
        return {"init": init, "whoami": whoami}[args.command](Path.cwd())
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
