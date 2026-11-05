"""Commands: init, config (check, show, sample), whoami (prove the API path works), sync."""

import argparse
import os
import stat
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

import httpx

from nile_tools import authentik, checks, config, idp, idp_run, lms, verify
from nile_tools.authentik import AuthentikError
from nile_tools.config import ConfigError
from nile_tools.contentfile import ContentError, load_course
from nile_tools.lms import LmsError
from nile_tools.sync import run_sync

__all__ = [
    "ConfigError",
    "config_check",
    "config_show",
    "idp_check",
    "idp_password_login",
    "idp_remove",
    "idp_setup",
    "init",
    "main",
    "sync",
    "verify_deploy",
    "whoami",
]


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


def sync(root: Path, *, check: bool) -> int:
    """Check `content/course.yaml`, then make the LMS match it (or only report with `check`)."""
    try:
        course = load_course(root / "content")
    except ContentError as e:
        for problem in e.problems:
            print(f"ERROR {problem}", file=sys.stderr)
        return 1
    values = config.load_env(root).values
    host, key, secret = (
        _require(values, k) for k in ("LMS_HOSTNAME", "LMS_API_KEY", "LMS_API_SECRET")
    )
    connection = lms.connect(host, key, secret)
    try:
        return run_sync(connection, course, check=check, say=print)
    except LmsError as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 1


def verify_deploy(root: Path) -> int:
    """Check the public site, the compose file and the MCP door; return 1 on any FAIL."""
    return verify.run(root, config.load_env(root).values)


def _lms_from_env(values: Mapping[str, str]) -> lms.Lms:
    host, key, secret = (
        _require(values, k) for k in ("LMS_HOSTNAME", "LMS_API_KEY", "LMS_API_SECRET")
    )
    return lms.connect(host, key, secret, retry_wait=5.0, read_tries=60)


def idp_password_login(root: Path, state: str) -> int:
    """Switch Frappe's password form on (break glass) or off."""
    values = config.load_env(root).values
    try:
        return idp_run.password_login(_lms_from_env(values), state, print)
    except (LmsError, idp.Refused) as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 1


def idp_setup(root: Path, *, resync_secret: bool = False) -> int:
    """Create or finish the Authentik application, provider and Frappe key."""
    values = config.load_env(root).values
    ak_host, token = (_require(values, k) for k in ("AUTHENTIK_HOSTNAME", "AUTHENTIK_API_TOKEN"))
    try:
        return idp_run.setup(
            authentik.connect(ak_host, token),
            _lms_from_env(values),
            values,
            print,
            resync_secret=resync_secret,
        )
    except (AuthentikError, LmsError, idp.ConfigProblem, idp.Refused) as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 1


def _authentik_from_env(values: Mapping[str, str]) -> authentik.Authentik:
    host, token = (_require(values, k) for k in ("AUTHENTIK_HOSTNAME", "AUTHENTIK_API_TOKEN"))
    return authentik.connect(host, token)


def idp_check(root: Path, *, user: str | None = None) -> int:
    """Report PASS, WARN or FAIL for each part of the Authentik sign in; write nothing."""
    values = config.load_env(root).values
    try:
        with httpx.Client(timeout=30) as public:
            return idp_run.check(
                _authentik_from_env(values), _lms_from_env(values), public, values, print, user=user
            )
    except (AuthentikError, LmsError, idp.ConfigProblem) as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 1


def idp_remove(root: Path) -> int:
    """Delete only the marked Frappe key, provider and application."""
    values = config.load_env(root).values
    try:
        return idp_run.remove(_authentik_from_env(values), _lms_from_env(values), values, print)
    except (AuthentikError, LmsError, idp.ConfigProblem) as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 1


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
    sync_cmd = commands.add_parser("sync", help="make the LMS course match content/course.yaml")
    sync_cmd.add_argument("--check", action="store_true", help="only list what would change")
    ver = commands.add_parser("verify", help="prove the deployment is reachable and safe")
    ver_actions = ver.add_subparsers(dest="action", required=True)
    ver_actions.add_parser("deploy", help="run every check")
    ver_actions.add_parser("services", help="list the long running services, one per line")
    idp_cmd = commands.add_parser("idp", help="set up the Authentik sign in")
    idp_actions = idp_cmd.add_subparsers(dest="action", required=True)
    setup_cmd = idp_actions.add_parser(
        "setup", help="create or fix the Authentik application and the Frappe key"
    )
    setup_cmd.add_argument(
        "--resync-secret",
        action="store_true",
        help="rewrite the Frappe client secret from Authentik",
    )
    check_cmd = idp_actions.add_parser("check", help="report PASS, WARN or FAIL, writing nothing")
    check_cmd.add_argument("--user", help="a real Authentik username, to test the groups claim")
    idp_actions.add_parser("remove", help="delete only the items setup created")
    pw_cmd = idp_actions.add_parser(
        "password-login", help="switch Frappe's own password form on (break glass) or off"
    )
    pw_cmd.add_argument("state", choices=["on", "off"])
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
        if args.command == "verify":
            if args.action == "services":
                print("\n".join(verify.long_running(verify.load_compose(root))))
                return 0
            return verify_deploy(root)
        if args.command == "idp":
            if args.action == "password-login":
                return idp_password_login(root, args.state)
            if args.action == "check":
                return idp_check(root, user=args.user)
            if args.action == "remove":
                return idp_remove(root)
            return idp_setup(root, resync_secret=args.resync_secret)
        if args.command == "sync":
            return sync(root, check=args.check)
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
