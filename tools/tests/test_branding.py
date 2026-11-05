"""Spec 0012: contrast of every text pair (AC-11) and the pure branding checks (AC-10)."""

import httpx
import pytest
from nile_auth import branding

from nile_tools.verify_branding import (
    Wanted,
    judge_default_format,
    judge_file,
    judge_print_format,
    judge_site_identity,
    judge_stylesheet,
)

WANTED = Wanted(
    format_name="Nile Certificate",
    app_name="Nile Learning",
    logo_url="/assets/nile_auth/images/nile-logo.png",
    icon_url="/assets/nile_auth/images/icon.png",
    stylesheet_url="/assets/nile_auth/css/nile-brand.css",
    stylesheet_built=False,
    logo_file="nile-logo.png",
    icon_file="icon.png",
)


@pytest.mark.parametrize(("name", "fg", "bg"), branding.TEXT_PAIRS)
def test_every_text_pair_passes_aa(name: str, fg: str, bg: str) -> None:
    assert branding.contrast_ratio(fg, bg) >= branding.MIN_CONTRAST, name


def test_contrast_known_values() -> None:
    assert branding.contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert branding.contrast_ratio("#FFFFFF", branding.NILE_BLUE) > 7
    # Solar Amber with white text fails, which is why amber carries no text.
    assert branding.contrast_ratio("#FFFFFF", branding.SOLAR_AMBER) < 4.5


def test_print_format_judge() -> None:
    assert judge_print_format({"disabled": 0}, "X").level == "PASS"
    assert judge_print_format({"disabled": 1}, "X").level == "FAIL"
    assert judge_print_format(None, "X").level == "FAIL"


def test_default_judge() -> None:
    assert judge_default_format("Nile Certificate", "Nile Certificate").level == "PASS"
    assert judge_default_format("Certificate", "Nile Certificate").level == "FAIL"
    assert judge_default_format(None, "Nile Certificate").level == "FAIL"


def test_site_identity_names_each_bad_item() -> None:
    lms_page = '<title>Nile Learning</title><link rel="icon" href="/other.png" />'
    login = f'<img class="app-logo" src="{WANTED.logo_url}">'
    levels = {r.name: r.level for r in judge_site_identity(lms_page, login, WANTED)}
    assert levels == {"site app name": "PASS", "site favicon": "FAIL", "site logo": "PASS"}


def test_file_judge() -> None:
    ok = httpx.Response(200, content=b"abc")
    assert judge_file("logo", "u", ok, b"abc").level == "PASS"
    changed = judge_file("logo", "u", ok, b"abd")
    assert changed.level == "FAIL"
    assert "optimizer" in changed.detail
    assert judge_file("logo", "u", httpx.Response(404), b"abc").level == "FAIL"
    assert judge_file("logo", "u", ok, None).level == "FAIL"


def test_stylesheet_judge() -> None:
    assert judge_stylesheet("u", httpx.Response(200)).level == "PASS"
    assert judge_stylesheet("u", httpx.Response(404)).level == "FAIL"
