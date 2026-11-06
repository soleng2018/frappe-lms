"""The key list, a strict .env parser, validators, generators, the sample and secret masking."""

import base64
import logging
import os
import re
import secrets
import sys
import traceback
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import Literal

__all__ = [
    "KEYS",
    "RETIRED_KEYS",
    "SCOPES",
    "ConfigError",
    "EnvFile",
    "Key",
    "add_missing",
    "check_values",
    "committed_keys",
    "delivery",
    "env_keys",
    "fill_generated",
    "generate_value",
    "install_masking",
    "load_env",
    "load_versions",
    "mask_value",
    "parse_env",
    "render_sample",
    "render_show",
    "scrub",
    "write_private",
]

Source = Literal["operator", "generated", "default", "committed"]


class ConfigError(Exception):
    """A config file or key is bad; the message names every bad key or line, never a value."""


@dataclass(frozen=True)
class Key:
    """One setting. The single declaration the sample, the checks and the compose wiring follow."""

    name: str
    group: str
    description: str
    source: Source
    secret: bool = False
    required_for: str | None = None
    validator: str | None = None
    generator: str | None = None
    default: str = ""
    frozen: bool = False
    services: tuple[tuple[str, str], ...] = ()  # (compose service, environment variable name)


KEYS: tuple[Key, ...] = (
    Key(
        "LMS_HOSTNAME",
        "LMS",
        "Public hostname. Site name, Traefik host rule, tools base URL",
        "operator",
        required_for="up",
        validator="hostname",
        frozen=True,
        services=(("create-site", "LMS_HOSTNAME"), ("frontend", "FRAPPE_SITE_NAME_HEADER")),
    ),
    Key(
        "LMS_ADMIN_PASSWORD",
        "LMS",
        "Frappe Administrator password",
        "generated",
        secret=True,
        required_for="up",
        generator="password",
        frozen=True,
        services=(("create-site", "LMS_ADMIN_PASSWORD"),),
    ),
    Key(
        "LMS_ENCRYPTION_KEY",
        "LMS",
        "Frappe encryption_key. Keep a private copy: restores need it",
        "generated",
        secret=True,
        required_for="up",
        validator="fernet",
        generator="fernet",
        frozen=True,
        services=(("create-site", "LMS_ENCRYPTION_KEY"),),
    ),
    Key(
        "LMS_SERVICE_USER",
        "LMS",
        "Service user id (email shaped) used by the tools",
        "default",
        required_for="up",
        validator="email",
        default="nile-tools@example.com",
        frozen=True,
        services=(("create-site", "LMS_SERVICE_USER"),),
    ),
    Key(
        "LMS_TIMEZONE",
        "LMS",
        "Site timezone (IANA name). New batches and the Desk use it",
        "default",
        required_for="up",
        validator="timezone",
        default="America/Los_Angeles",
        services=(("create-site", "LMS_TIMEZONE"),),
    ),
    Key(
        "LMS_API_KEY",
        "LMS",
        "Service user API key",
        "generated",
        secret=True,
        required_for="up",
        validator="hex32",
        generator="hex32",
        frozen=True,
        services=(("create-site", "LMS_API_KEY"),),
    ),
    Key(
        "LMS_API_SECRET",
        "LMS",
        "Service user API secret",
        "generated",
        secret=True,
        required_for="up",
        validator="hex32",
        generator="hex32",
        frozen=True,
        services=(("create-site", "LMS_API_SECRET"),),
    ),
    Key(
        "LMS_MCP_USER",
        "LMS",
        "MCP user id (email shaped) for your AI agent. Not the tools user",
        "default",
        required_for="up",
        validator="email",
        default="nile-mcp@example.com",
        frozen=True,
        services=(("create-site", "LMS_MCP_USER"),),
    ),
    Key(
        "LMS_MCP_API_KEY",
        "LMS",
        "MCP user API key. Rotate by editing it, then make up",
        "generated",
        secret=True,
        required_for="up",
        validator="hex32",
        generator="hex32",
        services=(("create-site", "LMS_MCP_API_KEY"),),
    ),
    Key(
        "LMS_MCP_API_SECRET",
        "LMS",
        "MCP user API secret. Rotate by editing it, then make up",
        "generated",
        secret=True,
        required_for="up",
        validator="hex32",
        generator="hex32",
        services=(("create-site", "LMS_MCP_API_SECRET"),),
    ),
    Key(
        "DB_ROOT_PASSWORD",
        "DB",
        "MariaDB root password. Ignored by MariaDB after first start",
        "generated",
        secret=True,
        required_for="up",
        generator="password",
        frozen=True,
        services=(("db", "MARIADB_ROOT_PASSWORD"), ("create-site", "DB_ROOT_PASSWORD")),
    ),
    Key(
        "AUTHENTIK_HOSTNAME",
        "AUTHENTIK",
        "Authentik hostname (the URL is https:// plus this)",
        "operator",
        required_for="up",
        validator="hostname",
    ),
    Key(
        "AUTHENTIK_API_TOKEN",
        "AUTHENTIK",
        "Authentik master API token",
        "operator",
        secret=True,
        required_for="tools-authentik",
    ),
    Key(
        "AUTHENTIK_APP_SLUG",
        "AUTHENTIK",
        "Slug of the Authentik application the script creates",
        "default",
        required_for="tools-authentik",
        default="nile-lms",
        frozen=True,
    ),
    Key(
        "AUTHENTIK_AUTHORIZATION_FLOW",
        "AUTHENTIK",
        "Slug of the Authentik authorization flow the LMS provider uses (no policy bindings)",
        "default",
        required_for="tools-authentik",
        default="default-provider-authorization-implicit-consent",
    ),
    Key(
        "AUTHENTIK_ADMIN_GROUP",
        "AUTHENTIK",
        "Group that becomes admin",
        "default",
        required_for="up",
        default="hol-admins",
        services=(("create-site", "AUTHENTIK_ADMIN_GROUP"),),
    ),
    Key(
        "TRAEFIK_NETWORK",
        "TRAEFIK",
        "External Docker network Traefik listens on",
        "default",
        required_for="up",
        default="traefik",
    ),
    Key(
        "TRAEFIK_ENTRYPOINT",
        "TRAEFIK",
        "Traefik entrypoint",
        "default",
        required_for="up",
        default="websecure",
    ),
    Key(
        "TRAEFIK_CERT_RESOLVER",
        "TRAEFIK",
        "Traefik certificate resolver",
        "default",
        required_for="up",
        default="letsencrypt",
    ),
    # Committed in deploy/versions.env, not in .env.
    Key(
        "BUILD_FRAPPE_DOCKER_TAG",
        "BUILD",
        "frappe_docker release used as build context",
        "committed",
    ),
    Key("BUILD_FRAPPE_TAG", "BUILD", "Frappe release tag", "committed"),
    Key("BUILD_LMS_TAG", "BUILD", "LMS release tag", "committed"),
    Key("BUILD_PYTHON_VERSION", "BUILD", "Python version of the Frappe image", "committed"),
    Key("BUILD_DEBIAN_BASE", "BUILD", "Debian release of the Frappe image", "committed"),
    Key("BUILD_PYTHON_BASE_DIGEST", "BUILD", "Digest of the Python base image", "committed"),
    Key("BUILD_NODE_VERSION", "BUILD", "Node version of the Frappe image", "committed"),
    Key("BUILD_BENCH_VERSION", "BUILD", "bench version", "committed"),
    Key("BUILD_NILE_AUTH_VERSION", "BUILD", "Version of the nile_auth app", "committed"),
    Key("DB_IMAGE", "BUILD", "MariaDB image, pinned by digest", "committed"),
    Key("REDIS_IMAGE", "BUILD", "Redis image, pinned by digest", "committed"),
    Key("TOOLS_PYTHON_IMAGE", "BUILD", "Python image of the tools container", "committed"),
)

# Which required_for values each `config check --for` scope enforces.
SCOPES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "up": ("up",),
        "tools-lms": ("up", "tools-lms"),
        "tools-authentik": ("up", "tools-authentik"),
    }
)

_VALUE = re.compile(r"^[A-Za-z0-9_.:/@+=,-]*$")
_LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
_LABEL = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_MIN_MASKED = 8  # shorter secrets are not scrubbed from text: they would mangle ordinary words


def env_keys() -> tuple[Key, ...]:
    """Return the keys that live in .env (everything not committed in versions.env)."""
    return tuple(k for k in KEYS if k.source != "committed")


def committed_keys() -> tuple[Key, ...]:
    """Return the keys that live in the committed deploy/versions.env."""
    return tuple(k for k in KEYS if k.source == "committed")


def delivery() -> Mapping[str, Mapping[str, str]]:
    """Return service -> {environment variable: KEY} as the key list declares it."""
    table: dict[str, dict[str, str]] = {}
    for key in KEYS:
        for service, var in key.services:
            table.setdefault(service, {})[var] = key.name
    return MappingProxyType({s: MappingProxyType(v) for s, v in table.items()})


# Validators return a problem phrase, or None when the value is fine.


def _hostname(value: str) -> str | None:
    labels = value.split(".")
    if len(value) > 253 or not all(_LABEL.match(label) for label in labels):
        return "is not a valid hostname (letters, digits and hyphens in dot separated labels)"
    return None


def _email(value: str) -> str | None:
    if not re.match(r"^[A-Za-z0-9._+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$", value):
        return "is not shaped like an email address"
    return None


def _hex32(value: str) -> str | None:
    return None if re.match(r"^[0-9a-f]{32}$", value) else "must be exactly 32 hex characters"


def _fernet(value: str) -> str | None:
    if re.match(r"^[A-Za-z0-9_-]{43}=$", value) and len(base64.urlsafe_b64decode(value)) == 32:
        return None
    return "must be 44 characters that urlsafe base64 decode to 32 bytes"


def _timezone(value: str) -> str | None:
    if value == "UTC" or re.match(r"^[A-Za-z_]+(/[A-Za-z0-9_+-]+)+$", value):
        return None
    return "must be an IANA timezone name such as America/Los_Angeles"


def _letters(value: str) -> str | None:
    return None if value.isascii() and value.isalpha() else "must be letters only"


VALIDATORS: Mapping[str, Callable[[str], str | None]] = MappingProxyType(
    {
        "hostname": _hostname,
        "email": _email,
        "hex32": _hex32,
        "fernet": _fernet,
        "letters": _letters,
        "timezone": _timezone,
    }
)


def _password() -> str:
    while True:
        value = secrets.token_urlsafe(24)
        if value[0].isalnum():  # a leading '-' could be read as a command flag
            return value


GENERATORS: Mapping[str, Callable[[], str]] = MappingProxyType(
    {
        "password": _password,
        "hex32": lambda: secrets.token_hex(16),
        "fernet": lambda: base64.urlsafe_b64encode(os.urandom(32)).decode(),
    }
)


def generate_value(key: Key) -> str:
    """Make a fresh value for a generated key."""
    if key.generator is None:
        raise ConfigError(f"{key.name} has no generator")
    return GENERATORS[key.generator]()


@dataclass(frozen=True)
class EnvFile:
    """A parsed dotenv file: values, the line each key was on, and every syntax problem found."""

    values: Mapping[str, str]
    lines: Mapping[str, int]
    errors: tuple[str, ...]


# Keys that earlier versions needed. A file that still holds one fails with a clear line.
RETIRED_KEYS = ("AUTHENTIK_STUDENT_GROUP_PREFIX", "AUTHENTIK_STUDENT_GROUP_SUFFIX")


def parse_env(text: str, known: Collection[str]) -> EnvFile:
    """Parse text with the strict dotenv subset, collecting every problem with its line number."""
    values: dict[str, str] = {}
    lines: dict[str, int] = {}
    errors: list[str] = []
    raw_lines = text.split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines.pop()
    for n, raw in enumerate(raw_lines, 1):
        if n == 1 and raw.startswith("﻿"):
            errors.append("line 1: file starts with a byte order mark")
            raw = raw.removeprefix("﻿")
        if raw.endswith("\r"):
            errors.append(f"line {n}: CRLF line end, use LF")
            raw = raw.removesuffix("\r")
        if raw != raw.rstrip():
            errors.append(f"line {n}: trailing spaces")
        if not raw.strip() or raw.startswith("#"):
            continue
        match = _LINE.match(raw)
        if not match:
            if raw.startswith("export "):
                errors.append(f"line {n}: 'export' is not allowed")
            elif "=" not in raw:
                errors.append(f"line {n}: no '=' (expected KEY=value)")
            else:
                errors.append(f"line {n}: bad key name (upper case letters, digits, _)")
            continue
        name, value = match.groups()
        if name in lines:
            errors.append(f"line {n}: {name} appears twice (first on line {lines[name]})")
            continue
        lines[name] = n
        if name in RETIRED_KEYS:
            errors.append(f"line {n}: {name} is retired, delete this line")
        elif name not in known and not name.startswith("COMPOSE_"):
            errors.append(f"line {n}: unknown key {name}")
        if not _VALUE.match(value):
            errors.append(
                f"line {n}: {name} has a character outside A-Za-z0-9_.:/@+=,- "
                "(no quotes, spaces, $, # or backslash)"
            )
            continue
        values[name] = value
    return EnvFile(MappingProxyType(values), MappingProxyType(lines), tuple(errors))


def check_values(env: EnvFile, keys: Iterable[Key], scope: str) -> tuple[str, ...]:
    """Return a problem for each key that is blank but needed for scope, or fails its validator."""
    needed = SCOPES[scope]
    problems: list[str] = []
    for key in keys:
        value = env.values.get(key.name, "")
        where = f"line {env.lines[key.name]}: " if key.name in env.lines else ""
        if not value:
            if key.name in env.lines and key.name not in env.values:
                continue  # its syntax error is already reported
            if key.required_for in needed:
                problems.append(f"{key.name} is missing or blank (needed for {key.required_for})")
            continue
        error = VALIDATORS[key.validator](value) if key.validator else None
        if error:
            problems.append(f"{where}{key.name} {error}")
    return tuple(problems)


def _heading(group: str) -> str:
    return f"# == {group} =="


def _block(key: Key) -> list[str]:
    note = " (fixed)" if key.frozen else ""
    note += " (generated)" if key.source == "generated" else ""
    return [f"# {key.description}{note}", f"{key.name}={key.default}"]


_HEADER = (
    "# Nile Workshop LMS settings. This file is generated: edit the key list in tools, not this.",
    "#",
    "# First run:",
    "#   1. make init     creates .env from this file and fills every generated secret",
    "#   2. edit .env     set the blank operator keys",
    "#   3. make check    then make up",
    "#",
    "# Never commit .env. Keep a private copy of it: without LMS_ENCRYPTION_KEY a restored",
    "# database cannot be read. (fixed) = never change after the first start.",
    "# (generated) = make init fills it for you.",
    "# A value may use only A-Za-z0-9_.:/@+=,- (no quotes, spaces, $ or #).",
)


def render_sample() -> str:
    """Build the .env.sample text from the key list: every .env key once, secrets blank."""
    out: list[str] = list(_HEADER)
    group = ""
    for key in env_keys():
        if key.group != group:
            group = key.group
            out += ["", _heading(group)]
        out += _block(key)
    return "\n".join(out) + "\n"


def add_missing(text: str, present: Collection[str]) -> str:
    """Append keys added to the key list since the file was made, under their group heading."""
    lines = text.rstrip("\n").split("\n") if text else []
    for key in env_keys():
        if key.name in present:
            continue
        block = _block(key)
        heading = _heading(key.group)
        if heading not in lines:
            lines += ["", heading, *block]
            continue
        at = lines.index(heading) + 1
        while at < len(lines) and not lines[at].startswith("# == "):
            at += 1
        while lines[at - 1] == "":
            at -= 1
        lines[at:at] = block
    return "\n".join(lines) + "\n"


def fill_generated(
    text: str, make: Callable[[Key], str] = generate_value, keys: Iterable[Key] = KEYS
) -> str:
    """Give every blank generated key a value; keys that already have one are never touched."""
    wanted = {k.name: k for k in keys if k.source == "generated"}
    out = []
    for line in text.split("\n"):
        name, sep, value = line.partition("=")
        if sep and not value and name in wanted:
            line = f"{name}={make(wanted[name])}"
        out.append(line)
    return "\n".join(out)


def mask_value(key: Key | None, value: str) -> str:
    """Show a set secret as ***** and any blank value as (blank)."""
    if not value:
        return "(blank)"
    return "*****" if key is None or key.secret else value


def render_show(values: Mapping[str, str]) -> str:
    """List every key with secrets masked."""
    by_name = {k.name: k for k in KEYS}
    rows = [f"{name}={mask_value(by_name.get(name), values.get(name, ''))}" for name in by_name]
    extras = [n for n in values if n not in by_name]
    rows += [f"{name}={mask_value(None, values[name])}" for name in extras]
    return "\n".join(rows) + "\n"


def scrub(text: str, values: Iterable[str]) -> str:
    """Replace every secret value found in text with *****."""
    for value in sorted({v for v in values if len(v) >= _MIN_MASKED}, key=len, reverse=True):
        text = text.replace(value, "*****")
    return text


def install_masking(values: Iterable[str]) -> None:
    """Scrub secret values from log records and from uncaught exception output."""
    secret_values = tuple(values)
    make_record = logging.getLogRecordFactory()

    def factory(*args: object, **kwargs: object) -> logging.LogRecord:
        record = make_record(*args, **kwargs)
        record.msg, record.args = scrub(record.getMessage(), secret_values), None
        return record

    def hook(kind: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
        text = "".join(traceback.format_exception(kind, exc, tb))
        sys.stderr.write(scrub(text, secret_values))

    logging.setLogRecordFactory(factory)
    sys.excepthook = hook


def write_private(path: Path, text: str) -> None:
    """Write text to path at mode 0600 through a temp file in the same folder, then rename."""
    tmp = path.with_name(".env.tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def _read(path: Path, known: Collection[str]) -> EnvFile:
    try:
        text = path.read_text()
    except OSError as e:
        hint = ": run make init" if path.name == ".env" and isinstance(e, FileNotFoundError) else ""
        raise ConfigError(f"{path.name} cannot be read ({e.strerror}){hint}") from e
    env = parse_env(text, known)
    if env.errors:
        raise ConfigError(f"{path.name} has problems:\n" + "\n".join(f"  {e}" for e in env.errors))
    return env


def load_env(root: Path, environ: Mapping[str, str] | None = None) -> EnvFile:
    """Read root/.env strictly; a process environment variable of a known key wins over the file."""
    env = _read(root / ".env", [k.name for k in env_keys()])
    environ = os.environ if environ is None else environ
    merged = {**env.values, **{k.name: environ[k.name] for k in env_keys() if k.name in environ}}
    return EnvFile(MappingProxyType(merged), env.lines, env.errors)


def load_versions(root: Path) -> EnvFile:
    """Read the committed deploy/versions.env with the same strict rules."""
    return _read(root / "deploy" / "versions.env", [k.name for k in committed_keys()])
