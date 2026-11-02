"""Commands: init, config (check, show, sample), whoami (prove the API path works)."""

import argparse
import os
import stat
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

import httpx

from nile_tools import checks, config
from nile_tools.config import ConfigError

__all__ = ["ConfigError", "config_check", "config_show", "init", "main", "whoami"]


def init(root: Path) -> int:
    """Create .env from the sample, fill blank generated secrets, report blank operator keys."""
    env = root / ".env"
    existed = env.exists()
    text = env.read_text() if existed else (root / ".env.sample").read_text()
    parsed = config.parse_env(text, [k.name for k in config.env_keys()])
    if parsed.errors:
        raise ConfigError(
            f"{env.name} has problems:\n" + "\n".join(f"  {e}" for e in parsed.errors)
        )
    new = config.fill_generated(config.add_missing(text, parsed.values))
    if new != text or not existed:
        config.write_private(env, new)
    elif stat.S_IMODE(env.stat().st_mode) & 0o077:
        env.chmod(0o600)
    state = "Created" if not existed else "Updated" if new != text else "Kept"
    print(f"{state} {env}")
    values = config.parse_env(new, [k.name for k in config.env_keys()]).values
    blank = [k for k in config.env_keys() if k.source == "operator" and not values.get(k.name)]
    required = [k.name for k in blank if k.required_for]
    optional = [k.name for k in blank if not k.required_for]
    if required:
        print(f"Still blank, fill these in: {', '.join(required)}")
    if optional:
        print(f"Optional, left blank: {', '.join(optional)}")
    return 0


def config_check(root: Path, scope: str) -> int:
    """Print every config problem at once and return 1 if there is any."""
    result = checks.check(root, scope, os.environ, checks.run_git(root))
    for problem in result.problems:
        print(f"ERROR {problem}", file=sys.stderr)
    for note in result.notes:
        print(note)
    if not result.problems:
        print(f"Config is fine for: {scope}")
    return 1 if result.problems else 0


def config_show(root: Path) -> int:
    """Print every key with secrets masked."""
    values = dict(config.load_env(root).values)
    versions = root / "deploy" / "versions.env"
    if versions.exists():
        values |= config.load_versions(root).values
    print(config.render_show(values), end="")
    return 0


def _require(values: Mapping[str, str], key: str) -> str:
    if not values.get(key):
        raise ConfigError(f"Config key {key} is missing or blank in .env")
    return values[key]


def whoami(root: Path) -> int:
    """Call the LMS API as the service user, retrying for 5 minutes, and print its name."""
    values = config.load_env(root).values
    host, key, secret = (
        _require(values, k) for k in ("LMS_HOSTNAME", "LMS_API_KEY", "LMS_API_SECRET")
    )
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


def _secret_values(root: Path) -> list[str]:
    """Return the secret values in .env, or none if the file cannot be read."""
    try:
        values = config.load_env(root).values
    except (OSError, ConfigError):
        return []
    return [values[k.name] for k in config.KEYS if k.secret and values.get(k.name)]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tools")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="create .env and generate missing secrets")
    commands.add_parser("whoami", help="prove the API path works")
    cfg = commands.add_parser("config", help="check, show or print the sample of the config file")
    actions = cfg.add_subparsers(dest="action", required=True)
    check = actions.add_parser("check", help="validate .env and the repo")
    check.add_argument("--for", dest="scope", choices=sorted(config.SCOPES), default="up")
    actions.add_parser("show", help="print every key, secrets masked")
    actions.add_parser("sample", help="print the .env.sample generated from the key list")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the named command; a ConfigError prints its message and exits 1."""
    args = _parser().parse_args(argv)
    root = Path.cwd()
    config.install_masking(_secret_values(root))
    try:
        if args.command == "init":
            return init(root)
        if args.command == "whoami":
            return whoami(root)
        if args.action == "check":
            return config_check(root, args.scope)
        if args.action == "show":
            return config_show(root)
        print(config.render_sample(), end="")
        return 0
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
