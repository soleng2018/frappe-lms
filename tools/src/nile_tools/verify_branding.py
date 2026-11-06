"""`verify branding` (spec 0012 AC-10): prove the Nile look is in place on the live site.

The judges are pure functions over records and responses. `run` reads the wanted values from
apps/nile_auth/nile_auth/branding.py (the one place they live), then does the network calls.
Plain `verify deploy` does not run these checks.
"""

import importlib.util
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx

from nile_tools import config, lms
from nile_tools.lms import LmsError
from nile_tools.verify import Result

__all__ = [
    "Wanted",
    "judge_default_format",
    "judge_file",
    "judge_icon_file_record",
    "judge_print_format",
    "judge_sidebar_logo",
    "judge_site_identity",
    "judge_stylesheet",
    "judge_stylesheet_linked",
    "load_wanted",
    "run",
]

BRANDING_PATH = Path("apps/nile_auth/nile_auth/branding.py")
BRAND_DIR = Path("brand")
TIMEOUT = 15.0
USER_AGENT = "nile-tools-verify/1.0"
# The byte compare would also fail if something between the site and us re encoded the image.
OPTIMIZATION_RISK = "a proxy or image optimizer may have changed the file"


@dataclass(frozen=True)
class Wanted:
    """What the branding constants say the site must show."""

    format_name: str
    app_name: str
    logo_url: str
    icon_url: str
    stylesheet_url: str
    stylesheet_built: bool
    logo_file: str
    icon_file: str


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("nile_auth_branding", path)
    if spec is None or spec.loader is None:
        raise config.ConfigError(f"cannot read {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_wanted(root: Path) -> Wanted:
    """Read the wanted values from branding.py in the repo."""
    path = root / BRANDING_PATH
    if not path.is_file():
        raise config.ConfigError(f"verify branding needs {path} (the branding constants)")
    m = _load_module(path)
    return Wanted(
        format_name=m.PRINT_FORMAT_NAME,
        app_name=m.APP_NAME,
        logo_url=m.LOGO_URL,
        icon_url=m.ICON_URL,
        stylesheet_url=m.STYLESHEET_URL,
        stylesheet_built=bool(m.STYLESHEET_BUILT),
        logo_file=m.LOGO_FILE,
        icon_file=m.ICON_FILE,
    )


def judge_print_format(record: Mapping[str, Any] | None, name: str) -> Result:
    """Check that the Print Format exists and is enabled."""
    label = f"Print Format {name}"
    if record is None:
        return Result("FAIL", "print format", f"{label} does not exist (run make up)")
    if record.get("disabled"):
        return Result("FAIL", "print format", f"{label} is disabled (the next make up enables it)")
    return Result("PASS", "print format", f"{label} exists and is enabled")


def judge_default_format(value: str | None, name: str) -> Result:
    """Check that LMS Certificate uses the Print Format by default."""
    if value == name:
        return Result("PASS", "default format", f"LMS Certificate defaults to {name}")
    return Result(
        "FAIL", "default format", f"LMS Certificate defaults to {value!r}, wanted {name!r}"
    )


def _first(pattern: str, page: str) -> str | None:
    m = re.search(pattern, page, re.IGNORECASE)
    return m.group(1).strip() if m else None


def judge_site_identity(lms_page: str, login_page: str, wanted: Wanted) -> list[Result]:
    """Check what a visitor sees: the page title and favicon on /lms, the logo on /login.

    The service user cannot read Website Settings, so the saved values are checked through the pages
    they feed (app_logo and banner_image both show as the same logo URL).
    """
    seen = {
        "app name": (_first(r"<title>\s*([^<]*)", lms_page), wanted.app_name),
        "favicon": (_first(r'rel="icon"\s+href="([^"]*)"', lms_page), wanted.icon_url),
        "logo": (_first(r'class="app-logo"\s+src="([^"]*)"', login_page), wanted.logo_url),
    }
    results = []
    for name, (got, value) in seen.items():
        if got == value:
            results.append(Result("PASS", f"site {name}", f"shows {value}"))
        else:
            results.append(Result("FAIL", f"site {name}", f"shows {got!r}, wanted {value!r}"))
    return results


def judge_icon_file_record(rows: Sequence[Mapping[str, Any]], url: str) -> Result:
    """Check that exactly one File record holds the shield URL (the LMS sidebar needs it)."""
    if len(rows) == 1:
        return Result("PASS", "icon file record", f"one File record holds {url}")
    if not rows:
        return Result("FAIL", "icon file record", f"no File record holds {url} (run make up)")
    return Result("FAIL", "icon file record", f"{len(rows)} File records hold {url}, wanted 1")


def judge_sidebar_logo(payload: Mapping[str, Any], url: str) -> Result:
    """Check that the guest get_branding call returns the shield as the sidebar logo."""
    banner = payload.get("message", {}).get("banner_image")
    got = banner.get("file_url") if isinstance(banner, Mapping) else None
    if got == url:
        return Result("PASS", "sidebar logo", f"get_branding banner_image is {url}")
    return Result("FAIL", "sidebar logo", f"get_branding banner_image is {got!r}, wanted {url!r}")


def judge_file(name: str, url: str, r: httpx.Response, expected: bytes | None) -> Result:
    """Check that a brand file answers 200 with the same bytes as the file in brand/."""
    if r.status_code != 200:
        return Result("FAIL", name, f"{url} answered {r.status_code}, wanted 200")
    if expected is None:
        return Result("FAIL", name, f"{url} answered 200 but the file in brand/ could not be read")
    if r.content != expected:
        return Result(
            "FAIL",
            name,
            f"{url} answered 200 with different bytes than brand/ ({OPTIMIZATION_RISK})",
        )
    return Result("PASS", name, f"{url} answers 200 with the same bytes as brand/")


def judge_stylesheet(url: str, r: httpx.Response) -> Result:
    """Check that the app stylesheet is served."""
    if r.status_code != 200:
        return Result("FAIL", "stylesheet", f"{url} answered {r.status_code}, wanted 200")
    return Result("PASS", "stylesheet", f"{url} answers 200")


def judge_stylesheet_linked(lms_page: str, url: str) -> Result:
    """Check that the LMS app page links the stylesheet (the nginx include is working)."""
    if url in lms_page:
        return Result("PASS", "stylesheet link", f"/lms links {url}")
    return Result("FAIL", "stylesheet link", f"/lms does not link {url} (the nginx include is off)")


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _fetch(client: httpx.Client, url: str) -> httpx.Response | str:
    try:
        # A query string skips an edge cache that may hold an old answer (a 404 from a restart).
        return client.get(
            url, params={"nile-verify": "1"}, headers={"Cache-Control": "no-transform"}
        )
    except httpx.HTTPError as e:
        return type(e).__name__


def _file_result(
    client: httpx.Client, name: str, base: str, url: str, expected: bytes | None
) -> Result:
    r = _fetch(client, base + url)
    if isinstance(r, str):
        return Result("FAIL", name, f"{base + url} could not be reached ({r})")
    return judge_file(name, base + url, r, expected)


def _sidebar_result(client: httpx.Client, base: str, icon_url: str) -> Result:
    url = f"{base}/api/method/lms.lms.api.get_branding"
    r = _fetch(client, url)
    if isinstance(r, str):
        return Result("FAIL", "sidebar logo", f"{url} could not be reached ({r})")
    if r.status_code != 200:
        return Result("FAIL", "sidebar logo", f"{url} answered {r.status_code}, wanted 200")
    try:
        payload = r.json()
    except ValueError:
        return Result("FAIL", "sidebar logo", f"{url} did not answer JSON")
    return judge_sidebar_logo(payload if isinstance(payload, dict) else {}, icon_url)


def _record_or_none(fetch: Callable[[], Mapping[str, Any]]) -> Mapping[str, Any] | None:
    try:
        return fetch()
    except LmsError as e:
        if "404" in str(e) or "not found" in str(e).lower():
            return None
        raise


def run(
    root: Path,
    values: Mapping[str, str],
    *,
    say: Callable[[str], None] = print,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """Print one line per branding item and return 1 if any fails. Never prints a secret."""
    wanted = load_wanted(root)
    host = values["LMS_HOSTNAME"]
    base = f"https://{host}"
    conn = lms.connect(host, values["LMS_API_KEY"], values["LMS_API_SECRET"], transport=transport)
    results: list[Result] = []
    try:
        fmt = _record_or_none(lambda: lms.get_record(conn, "Print Format", wanted.format_name))
        results.append(judge_print_format(fmt, wanted.format_name))
        setters = lms.list_records(
            conn,
            "Property Setter",
            filters=[
                ["doc_type", "=", "LMS Certificate"],
                ["property", "=", "default_print_format"],
            ],
            fields=("value",),
        )
        results.append(
            judge_default_format(setters[0].get("value") if setters else None, wanted.format_name)
        )
        icon_rows = lms.list_records(
            conn, "File", filters=[["file_url", "=", wanted.icon_url]], fields=("name",)
        )
        results.append(judge_icon_file_record(icon_rows, wanted.icon_url))
    except LmsError as e:
        results.append(Result("FAIL", "site records", str(e)))
    finally:
        conn.http.close()

    with httpx.Client(
        timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, transport=transport
    ) as client:
        pages = [_fetch(client, base + path) for path in ("/lms", "/login")]
        if all(isinstance(r, httpx.Response) and r.status_code == 200 for r in pages):
            texts = [r.text for r in pages if isinstance(r, httpx.Response)]
            results.extend(judge_site_identity(texts[0], texts[1], wanted))
            if wanted.stylesheet_built:
                results.append(judge_stylesheet_linked(texts[0], wanted.stylesheet_url))
        else:
            results.append(
                Result("FAIL", "site identity", f"{base}/lms or /login did not answer 200")
            )
        results.append(_sidebar_result(client, base, wanted.icon_url))
        results.append(
            _file_result(
                client, "logo", base, wanted.logo_url, _read(root / BRAND_DIR / wanted.logo_file)
            )
        )
        results.append(
            _file_result(
                client, "icon", base, wanted.icon_url, _read(root / BRAND_DIR / wanted.icon_file)
            )
        )
        if wanted.stylesheet_built:
            r = _fetch(client, base + wanted.stylesheet_url)
            if isinstance(r, str):
                results.append(
                    Result(
                        "FAIL", "stylesheet", f"{base + wanted.stylesheet_url} unreachable ({r})"
                    )
                )
            else:
                results.append(judge_stylesheet(base + wanted.stylesheet_url, r))

    for result in results:
        say(result.line())
    fails = [r for r in results if r.level == "FAIL"]
    say(f"{len(results)} checks: {len(fails)} FAIL")
    return 1 if fails else 0
