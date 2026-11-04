"""The `verify deploy` checks (spec 0007): public URL checks and a static look at the compose file.

Every check is a pure function from a response or a parsed compose file to a `Result`. Only
`probe` and `run` touch the network and the disk.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit

import httpx
import yaml

from nile_tools.config import ConfigError

__all__ = [
    "REQUIRED_KEYS",
    "Assets",
    "Result",
    "Settings",
    "compose_results",
    "judge_asset",
    "judge_home",
    "judge_ping",
    "judge_redirect",
    "judge_socketio",
    "load_settings",
    "long_running",
    "parse_assets",
    "public_results",
    "run",
]

Level = Literal["PASS", "WARN", "FAIL"]

REQUIRED_KEYS = ("LMS_HOSTNAME",)
TIMEOUT = 10.0
USER_AGENT = "nile-tools-verify/1.0"
MAX_ASSETS = 5  # per type
REDIRECT_STATUSES = (301, 302, 307, 308)
# Expected log and restart settings (spec 0001).
LOG_DRIVER = "json-file"
LOG_MAX_SIZE = "10m"
LOG_MAX_FILE = "5"
RESTART_POLICY = "unless-stopped"
TRAEFIK_NETWORK = "traefik"
HOST_RULE = "Host(`${LMS_HOSTNAME}`)"


@dataclass(frozen=True)
class Result:
    """One check outcome. `detail` names the URL or compose key and never holds a secret."""

    level: Level
    name: str
    detail: str

    def line(self) -> str:
        """Return the printable `LEVEL name: detail` line."""
        return f"{self.level} {self.name}: {self.detail}"


@dataclass(frozen=True)
class Settings:
    """The values `verify deploy` needs from .env."""

    host: str


@dataclass(frozen=True)
class Assets:
    """Same host asset paths found on the home page, query strings kept."""

    css: tuple[str, ...]
    js: tuple[str, ...]


def load_settings(values: Mapping[str, str]) -> Settings:
    """Return the settings, or raise one ConfigError naming every missing key."""
    missing = [k for k in REQUIRED_KEYS if not values.get(k)]
    if missing:
        raise ConfigError(
            f"verify deploy needs these keys in .env: {', '.join(missing)} (run make init)"
        )
    return Settings(host=values["LMS_HOSTNAME"])


# --- public checks: pure judges over a response ---


def _status_note(r: httpx.Response) -> str:
    """Describe an unexpected status, calling out a Cloudflare challenge."""
    challenge = r.status_code == 403 and (
        r.headers.get("cf-mitigated") == "challenge" or "cloudflare" in r.headers.get("server", "")
    )
    return (
        "HTTP 403 (a Cloudflare challenge, not the LMS)" if challenge else f"HTTP {r.status_code}"
    )


def judge_ping(url: str, r: httpx.Response) -> Result:
    """Pass on 200 with {"message": "pong"}."""
    if r.status_code != 200:
        return Result("FAIL", "ping", f"{url} gave {_status_note(r)}, expected 200")
    try:
        message = r.json().get("message")
    except (ValueError, AttributeError):
        message = None
    if message != "pong":
        return Result("FAIL", "ping", f'{url} gave 200 but the body is not {{"message":"pong"}}')
    return Result("PASS", "ping", f"{url} gave 200 pong")


class _AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.css: list[str] = []
        self.js: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "link" and a.get("href"):
            rel = (a.get("rel") or "").lower().split()
            if "stylesheet" in rel:
                self.css.append(a["href"] or "")
            elif "modulepreload" in rel:
                self.js.append(a["href"] or "")
        elif tag == "script" and a.get("src"):
            self.js.append(a["src"] or "")


def parse_assets(page: str, base_url: str) -> Assets:
    """Find the first CSS and JS files under /assets/ on the same host as base_url."""
    parser = _AssetParser()
    parser.feed(page)
    host = urlsplit(base_url).netloc

    def keep(hrefs: Sequence[str]) -> tuple[str, ...]:
        found: list[str] = []
        for href in hrefs:
            full = urljoin(base_url, href)
            parts = urlsplit(full)
            if parts.netloc != host or not parts.path.startswith("/assets/"):
                continue
            path = parts.path + (f"?{parts.query}" if parts.query else "")
            if path not in found:
                found.append(path)
        return tuple(found[:MAX_ASSETS])

    return Assets(css=keep(parser.css), js=keep(parser.js))


def judge_home(r: httpx.Response) -> Result:
    """Pass on a 200 HTML page; the final URL after redirects is printed."""
    final = str(r.url)
    if r.status_code != 200:
        return Result("FAIL", "home page", f"{final} gave {_status_note(r)}, expected 200")
    if "text/html" not in r.headers.get("content-type", ""):
        return Result("FAIL", "home page", f"{final} gave 200 but not HTML")
    return Result("PASS", "home page", f"{final} gave 200 HTML")


def judge_asset(url: str, r: httpx.Response) -> Result:
    """Pass when one asset file returns 200."""
    if r.status_code != 200:
        return Result("FAIL", "asset", f"{url} gave {_status_note(r)}, expected 200")
    return Result("PASS", "asset", f"{url} gave 200")


def judge_socketio(url: str, r: httpx.Response) -> Result:
    """Pass on 200 with a polling handshake body that starts with `0{`."""
    if r.status_code != 200:
        return Result("FAIL", "socket.io", f"{url} gave {_status_note(r)}, expected 200")
    if not r.text.startswith("0{"):
        return Result("FAIL", "socket.io", f"{url} gave 200 but the body does not start with 0{{")
    return Result("PASS", "socket.io", f"{url} handshake ok")


def judge_redirect(url: str, r: httpx.Response) -> Result:
    """Pass when plain HTTP redirects to https. Anything else is a WARN, never a FAIL."""
    location = r.headers.get("location", "")
    if r.status_code in REDIRECT_STATUSES and location.startswith("https://"):
        return Result("PASS", "http redirect", f"{url} gave {r.status_code} to {location}")
    return Result(
        "WARN",
        "http redirect",
        f"{url} gave HTTP {r.status_code} with no redirect to https. "
        "Turn on Always Use HTTPS in Cloudflare (see README)",
    )


# --- public checks: the network edge ---


def _get(client: httpx.Client, url: str, **kwargs: Any) -> httpx.Response | str:
    """GET a URL. Returns the response, or the error class name on a network failure."""
    try:
        return client.get(url, **kwargs)
    except httpx.HTTPError as e:
        return type(e).__name__


def _unreachable(name: str, url: str, error: str, level: Level = "FAIL") -> Result:
    return Result(level, name, f"{url} could not be reached ({error})")


def public_results(client: httpx.Client, host: str) -> list[Result]:
    """Run the checks that need only the public hostname."""
    base = f"https://{host}"
    results: list[Result] = []

    ping_url = f"{base}/api/method/ping"
    ping = _get(client, ping_url)
    results.append(
        _unreachable("ping", ping_url, ping)
        if isinstance(ping, str)
        else judge_ping(ping_url, ping)
    )

    home = _get(client, f"{base}/", follow_redirects=True)
    if isinstance(home, str):
        results.append(_unreachable("home page", f"{base}/", home))
    else:
        results.append(judge_home(home))
        if home.status_code == 200:
            results += _asset_results(client, home, base)

    sock_url = f"{base}/socket.io/?EIO=4&transport=polling"
    sock = _get(client, sock_url)
    results.append(
        _unreachable("socket.io", sock_url, sock)
        if isinstance(sock, str)
        else judge_socketio(sock_url, sock)
    )

    plain_url = f"http://{host}/"
    plain = _get(client, plain_url, follow_redirects=False)
    results.append(
        _unreachable("http redirect", plain_url, plain, "WARN")
        if isinstance(plain, str)
        else judge_redirect(plain_url, plain)
    )
    return results


def _asset_results(client: httpx.Client, home: httpx.Response, base: str) -> list[Result]:
    assets = parse_assets(home.text, str(home.url))
    results: list[Result] = []
    for kind, paths in (("CSS", assets.css), ("JS", assets.js)):
        if not paths:
            results.append(
                Result("FAIL", "asset", f"{home.url} lists no {kind} file under /assets/")
            )
        for path in paths:
            url = f"{base}{path}"
            fetched = _get(client, url)
            results.append(
                _unreachable("asset", url, fetched)
                if isinstance(fetched, str)
                else judge_asset(url, fetched)
            )
    return results


# --- compose checks: pure over the parsed file ---


def _services(compose: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {n: s for n, s in (compose.get("services") or {}).items() if isinstance(s, Mapping)}


def _depends(service: Mapping[str, Any]) -> dict[str, str]:
    """Return {dependency: condition}, whether depends_on is a list or a mapping."""
    raw = service.get("depends_on") or {}
    if isinstance(raw, Mapping):
        return {n: str((c or {}).get("condition", "service_started")) for n, c in raw.items()}
    return dict.fromkeys(raw, "service_started")


def long_running(compose: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the services that stay up: no profile, and not a one shot that others wait on."""
    services = _services(compose)
    one_shots = {
        dep
        for s in services.values()
        for dep, cond in _depends(s).items()
        if cond == "service_completed_successfully"
    }
    return tuple(n for n, s in services.items() if not s.get("profiles") and n not in one_shots)


def _labels(service: Mapping[str, Any]) -> dict[str, str]:
    raw = service.get("labels") or {}
    if isinstance(raw, Mapping):
        return {str(k): str(v) for k, v in raw.items()}
    return {str(k): str(v) for k, _, v in (item.partition("=") for item in raw)}


def _network_names(service: Mapping[str, Any]) -> list[str]:
    raw = service.get("networks") or []
    return [str(n) for n in raw]


def _check_ports(services: Mapping[str, Mapping[str, Any]]) -> Result:
    published = sorted(n for n, s in services.items() if s.get("ports"))
    if published:
        return Result(
            "FAIL", "compose ports", f"services.{', '.join(published)}.ports publishes a port"
        )
    return Result("PASS", "compose ports", "no service publishes a port")


def _check_traefik(services: Mapping[str, Mapping[str, Any]]) -> list[Result]:
    labelled = sorted(
        n for n, s in services.items() if any(k.startswith("traefik.") for k in _labels(s))
    )
    networked = sorted(n for n, s in services.items() if TRAEFIK_NETWORK in _network_names(s))
    results: list[Result] = []
    if labelled != ["frontend"]:
        results.append(
            Result(
                "FAIL",
                "compose labels",
                f"traefik labels are on {labelled or 'no service'}, want only frontend",
            )
        )
    else:
        results.append(Result("PASS", "compose labels", "only frontend has traefik labels"))
    if networked != ["frontend"]:
        results.append(
            Result(
                "FAIL",
                "compose networks",
                f"the traefik network is on {networked or 'no service'}, want only frontend",
            )
        )
    else:
        results.append(
            Result("PASS", "compose networks", "only frontend joins the traefik network")
        )
    rules = {k: v for k, v in _labels(services.get("frontend", {})).items() if k.endswith(".rule")}
    if rules and all(HOST_RULE in v for v in rules.values()):
        results.append(Result("PASS", "compose rule", f"router rule names {HOST_RULE}"))
    else:
        results.append(
            Result(
                "FAIL",
                "compose rule",
                f"services.frontend.labels has no router rule using {HOST_RULE}",
            )
        )
    return results


def _check_logging(services: Mapping[str, Mapping[str, Any]]) -> Result:
    bad: list[str] = []
    for name, s in services.items():
        log = s.get("logging") or {}
        options = log.get("options") or {}
        if (
            log.get("driver") != LOG_DRIVER
            or str(options.get("max-size")) != LOG_MAX_SIZE
            or str(options.get("max-file")) != LOG_MAX_FILE
        ):
            bad.append(name)
    if bad:
        return Result(
            "FAIL",
            "compose logging",
            f"services.{', '.join(sorted(bad))}.logging must be {LOG_DRIVER}, "
            f"max-size {LOG_MAX_SIZE}, max-file {LOG_MAX_FILE}",
        )
    return Result(
        "PASS", "compose logging", f"every service rotates logs ({LOG_MAX_SIZE} x {LOG_MAX_FILE})"
    )


def _check_restart(compose: Mapping[str, Any]) -> Result:
    services = _services(compose)
    bad = [n for n in long_running(compose) if services[n].get("restart") != RESTART_POLICY]
    if bad:
        return Result(
            "FAIL",
            "compose restart",
            f"services.{', '.join(sorted(bad))}.restart must be {RESTART_POLICY}",
        )
    return Result("PASS", "compose restart", f"every long running service is {RESTART_POLICY}")


def compose_results(compose: Mapping[str, Any]) -> list[Result]:
    """Return the static checks over a parsed compose file."""
    services = _services(compose)
    return [
        _check_ports(services),
        *_check_traefik(services),
        _check_logging(services),
        _check_restart(compose),
    ]


# --- the command ---


def load_compose(root: Path) -> Mapping[str, Any]:
    """Read deploy/compose.yaml raw, so ${...} stays as written and anchors are merged."""
    path = root / "deploy" / "compose.yaml"
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"{path} cannot be read as compose YAML ({type(e).__name__})") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path} is not a compose mapping")
    return data


def probe(settings: Settings, *, transport: httpx.BaseTransport | None = None) -> list[Result]:
    """Run every public check against the live hostname."""
    with httpx.Client(
        timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, transport=transport
    ) as client:
        return public_results(client, settings.host)


def run(
    root: Path,
    values: Mapping[str, str],
    *,
    say: Callable[[str], None] = print,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """Run all checks, print one line each, and return 1 only if any is a FAIL."""
    settings = load_settings(values)
    results = [*probe(settings, transport=transport), *compose_results(load_compose(root))]
    for result in results:
        say(result.line())
    fails = sum(r.level == "FAIL" for r in results)
    warns = sum(r.level == "WARN" for r in results)
    say(f"{len(results)} checks: {fails} FAIL, {warns} WARN")
    return 1 if fails else 0
