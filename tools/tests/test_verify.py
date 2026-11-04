"""Unit tests for `verify deploy`: canned responses and compose samples, no network."""

from pathlib import Path

import httpx
import pytest
import yaml

from nile_tools import verify
from nile_tools.config import ConfigError

REPO = Path(__file__).resolve().parents[2]
HOST = "lms.example.com"
MCP_URL = f"https://{HOST}/api/v2/mcp"
SETTINGS = verify.Settings(HOST, "k" * 32, "s" * 32)
RPC = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18"}}
HOME = (
    '<html><head><link rel="stylesheet" href="/assets/a.css?v=1">'
    '<link rel="modulepreload" href="/assets/m.js"></head>'
    '<body><script src="/assets/b.js"></script><script src="https://cdn.x/y.js"></script>'
    "</body></html>"
)


def _handler(overrides: dict[str, httpx.Response] | None = None):
    table = {
        f"https://{HOST}/api/method/ping": httpx.Response(200, json={"message": "pong"}),
        f"https://{HOST}/": httpx.Response(200, text=HOME, headers={"content-type": "text/html"}),
        f"https://{HOST}/assets/a.css?v=1": httpx.Response(200),
        f"https://{HOST}/assets/m.js": httpx.Response(200),
        f"https://{HOST}/assets/b.js": httpx.Response(200),
        f"https://{HOST}/socket.io/?EIO=4&transport=polling": httpx.Response(
            200, text='0{"sid":1}'
        ),
        f"http://{HOST}/": httpx.Response(301, headers={"location": f"https://{HOST}/"}),
        **(overrides or {}),
    }

    def handle(request: httpx.Request) -> httpx.Response:
        if str(request.url) == MCP_URL:
            if "authorization" in request.headers:
                return table.get("mcp-key", httpx.Response(200, json=RPC))
            return table.get("mcp-guest", httpx.Response(401, text="AuthenticationError: no"))
        return table[str(request.url)]

    return httpx.MockTransport(handle)


VALUES = {
    "LMS_HOSTNAME": HOST,
    "LMS_MCP_USER": "nile-mcp@example.com",
    "LMS_MCP_API_KEY": "k" * 32,
    "LMS_MCP_API_SECRET": "s" * 32,
}


def _levels(results: list[verify.Result]) -> dict[str, str]:
    return {r.name: r.level for r in results}


def test_everything_good_passes():
    results = verify.probe(SETTINGS, transport=_handler())
    assert {r.level for r in results} == {"PASS"}
    assert len([r for r in results if r.name == "asset"]) == 3


@pytest.mark.parametrize(
    ("url", "response", "name"),
    [
        (f"https://{HOST}/api/method/ping", httpx.Response(200, json={"message": "x"}), "ping"),
        (f"https://{HOST}/api/method/ping", httpx.Response(502), "ping"),
        (
            f"https://{HOST}/socket.io/?EIO=4&transport=polling",
            httpx.Response(200, text="no"),
            "socket.io",
        ),
        (f"https://{HOST}/assets/b.js", httpx.Response(404), "asset"),
        (
            f"https://{HOST}/",
            httpx.Response(200, text="<p>", headers={"content-type": "text/html"}),
            "asset",
        ),
    ],
)
def test_bad_responses_fail(url, response, name):
    results = verify.probe(SETTINGS, transport=_handler({url: response}))
    assert "FAIL" in [r.level for r in results if r.name == name]


def test_cloudflare_challenge_is_named():
    r = httpx.Response(403, headers={"cf-mitigated": "challenge"})
    result = verify.judge_ping("u", r)
    assert result.level == "FAIL"
    assert "Cloudflare" in result.detail


def test_http_200_is_a_warn_not_a_fail():
    results = verify.probe(SETTINGS, transport=_handler({f"http://{HOST}/": httpx.Response(200)}))
    assert _levels(results)["http redirect"] == "WARN"
    assert "Always Use HTTPS" in next(r for r in results if r.name == "http redirect").detail


def test_redirect_to_http_is_a_warn():
    r = httpx.Response(301, headers={"location": "http://x/"})
    assert verify.judge_redirect("u", r).level == "WARN"


def test_network_failure_names_the_url():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no")

    results = verify.probe(SETTINGS, transport=httpx.MockTransport(boom))
    ping = next(r for r in results if r.name == "ping")
    assert ping.level == "FAIL"
    assert f"https://{HOST}/api/method/ping" in ping.detail
    assert next(r for r in results if r.name == "http redirect").level == "WARN"


def test_parse_assets_keeps_query_and_same_host_only():
    assets = verify.parse_assets(HOME, f"https://{HOST}/")
    assert assets.css == ("/assets/a.css?v=1",)
    assert assets.js == ("/assets/m.js", "/assets/b.js")


def test_missing_keys_are_named_together():
    with pytest.raises(ConfigError, match="LMS_HOSTNAME"):
        verify.load_settings({})


# --- compose ---


def _compose() -> dict:
    return yaml.safe_load((REPO / "deploy/compose.yaml").read_text())


def test_real_compose_passes_every_static_check():
    results = verify.compose_results(_compose())
    assert {r.level for r in results} == {"PASS"}


def test_long_running_excludes_one_shots_and_profiles():
    names = verify.long_running(_compose())
    assert "frontend" in names
    assert not {"configurator", "create-site", "tools"} & set(names)


def test_long_running_skips_a_profile_service_and_a_one_shot_others_wait_on():
    c = _compose()
    c["services"]["extra"] = {"profiles": ["tools"]}
    c["services"]["setup"] = {}
    c["services"]["app"] = {
        "depends_on": {"setup": {"condition": "service_completed_successfully"}}
    }
    names = verify.long_running(c)
    assert "extra" not in names
    assert "setup" not in names
    assert "app" in names


def test_home_page_without_assets_fails_for_css_and_js():
    page = httpx.Response(
        200,
        text="<html><body>no files</body></html>",
        headers={"content-type": "text/html"},
        request=httpx.Request("GET", f"https://{HOST}/"),
    )
    with httpx.Client(transport=_handler()) as client:
        results = verify._asset_results(client, page, f"https://{HOST}")
    assert [r.level for r in results] == ["FAIL", "FAIL"]
    assert all(HOST in r.line() for r in results)


def test_only_the_first_five_assets_of_each_type_are_fetched():
    page = "".join(f'<link rel="stylesheet" href="/assets/{i}.css">' for i in range(8))
    page += "".join(f'<script src="/assets/{i}.js"></script>' for i in range(8))
    assets = verify.parse_assets(page, f"https://{HOST}/")
    assert assets.css == tuple(f"/assets/{i}.css" for i in range(5))
    assert assets.js == tuple(f"/assets/{i}.js" for i in range(5))


def test_published_port_fails():
    c = _compose()
    c["services"]["backend"]["ports"] = ["8000:8000"]
    assert _levels(verify.compose_results(c))["compose ports"] == "FAIL"


def test_missing_max_file_fails():
    c = _compose()
    c["services"]["db"]["logging"] = {"driver": "json-file", "options": {"max-size": "10m"}}
    assert _levels(verify.compose_results(c))["compose logging"] == "FAIL"


def test_label_on_other_service_and_network_fail():
    c = _compose()
    c["services"]["backend"]["labels"] = {"traefik.enable": "true"}
    c["services"]["backend"]["networks"] = ["default", "traefik"]
    levels = _levels(verify.compose_results(c))
    assert levels["compose labels"] == levels["compose networks"] == "FAIL"


def test_wrong_host_rule_and_missing_restart_fail():
    c = _compose()
    labels = c["services"]["frontend"]["labels"]
    labels["traefik.http.routers.nile-lms.rule"] = "Host(`other.example.com`)"
    c["services"]["queue-long"]["restart"] = "no"
    levels = _levels(verify.compose_results(c))
    assert levels["compose rule"] == "FAIL"
    assert levels["compose restart"] == "FAIL"


def test_run_exit_codes_and_no_fail_on_warn(tmp_path):
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy/compose.yaml").write_text((REPO / "deploy/compose.yaml").read_text())
    lines: list[str] = []
    code = verify.run(
        tmp_path,
        VALUES,
        say=lines.append,
        transport=_handler({f"http://{HOST}/": httpx.Response(200)}),
    )
    assert code == 0
    assert any(line.startswith("WARN http redirect") for line in lines)
    bad = verify.run(
        tmp_path,
        VALUES,
        say=lines.append,
        transport=_handler({f"https://{HOST}/api/method/ping": httpx.Response(500)}),
    )
    assert bad == 1


# --- mcp ---


def test_mcp_guest_must_be_401_authentication():
    for response in (httpx.Response(200, json=RPC), httpx.Response(401, text="nope")):
        results = verify.probe(SETTINGS, transport=_handler({"mcp-guest": response}))
        assert _levels(results)["mcp without key"] == "FAIL"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403, text="Forbidden"),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"jsonrpc": "2.0", "error": {}}),
    ],
)
def test_mcp_with_key_failures(response):
    results = verify.probe(SETTINGS, transport=_handler({"mcp-key": response}))
    assert _levels(results)["mcp with key"] == "FAIL"


def test_mcp_with_key_accepts_an_sse_data_line():
    sse = httpx.Response(200, text='event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n')
    results = verify.probe(SETTINGS, transport=_handler({"mcp-key": sse}))
    assert _levels(results)["mcp with key"] == "PASS"


def test_output_never_holds_the_key_or_secret(tmp_path):
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy/compose.yaml").write_text((REPO / "deploy/compose.yaml").read_text())
    lines: list[str] = []
    values = {
        "LMS_HOSTNAME": HOST,
        "LMS_MCP_USER": "nile-mcp@example.com",
        "LMS_MCP_API_KEY": "k" * 32,
        "LMS_MCP_API_SECRET": "s" * 32,
    }
    bad = _handler({"mcp-key": httpx.Response(403, text="k" * 32)})
    verify.run(tmp_path, values, say=lines.append, transport=bad)
    assert "k" * 32 not in "\n".join(lines)
    assert "s" * 32 not in "\n".join(lines)


def test_all_missing_mcp_keys_are_named_at_once():
    with pytest.raises(ConfigError) as e:
        verify.load_settings({"LMS_HOSTNAME": HOST})
    for key in ("LMS_MCP_USER", "LMS_MCP_API_KEY", "LMS_MCP_API_SECRET"):
        assert key in str(e.value)
