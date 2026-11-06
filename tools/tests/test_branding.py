"""Spec 0012: contrast of every text pair (AC-11) and the pure branding checks (AC-10)."""

import httpx
import pytest
from nile_auth import branding

from nile_tools.verify_branding import (
    Wanted,
    judge_default_format,
    judge_file,
    judge_icon_file_record,
    judge_print_format,
    judge_sidebar_logo,
    judge_site_identity,
    judge_stylesheet,
    judge_stylesheet_linked,
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


def test_stylesheet_link_judge() -> None:
    url = WANTED.stylesheet_url
    assert judge_stylesheet_linked(f'<link href="{url}">', url).level == "PASS"
    assert judge_stylesheet_linked("<html></html>", url).level == "FAIL"


def test_icon_file_record_judge() -> None:
    url = WANTED.icon_url
    assert judge_icon_file_record([{"name": "a"}], url).level == "PASS"
    assert judge_icon_file_record([], url).level == "FAIL"
    assert judge_icon_file_record([{"name": "a"}, {"name": "b"}], url).level == "FAIL"


def test_sidebar_logo_judge() -> None:
    url = WANTED.icon_url
    assert judge_sidebar_logo({"message": {"banner_image": {"file_url": url}}}, url).level == "PASS"
    wide = {"message": {"banner_image": {"file_url": WANTED.logo_url}}}
    assert judge_sidebar_logo(wide, url).level == "FAIL"
    # No File record: LMS returns the bare value or nothing, never a file_url.
    assert judge_sidebar_logo({"message": {"banner_image": None}}, url).level == "FAIL"
    assert judge_sidebar_logo({}, url).level == "FAIL"


def test_site_identity_wants_the_shield_on_the_sidebar_and_the_wide_logo_elsewhere() -> None:
    assert branding.SITE_IDENTITY["banner_image"] == branding.ICON_URL
    assert branding.SITE_IDENTITY["favicon"] == branding.ICON_URL
    assert branding.SITE_IDENTITY["app_logo"] == branding.LOGO_URL


def test_changed_values_returns_only_the_differences() -> None:
    wanted = {"a": 1, "b": 2}
    assert branding.changed_values({"a": 1, "b": 9}, wanted) == {"b": 2}
    assert branding.changed_values({"a": 1, "b": 2}, wanted) == {}
    assert branding.changed_values({}, wanted) == wanted
