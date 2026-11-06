"""Spec 0012 on the running site: the issued certificate is the Nile design (-m integration).

Reuses the throwaway course and users of the spec 0010 test, so everything is removed afterwards.
"""

import io
from typing import Any

import pytest
from pypdf import PdfReader
from test_pass_certificate_integration import (  # noqa: F401  (world is a fixture)
    World,
    _site,
    _sql,
    attempt,
    certificate_name,
    complete,
    open_link,
    request_certificate,
    set_published,
    world,
)

pytestmark = pytest.mark.integration


def _resources(reader: PdfReader) -> Any:
    return reader.pages[0]["/Resources"]


def _fonts(reader: PdfReader) -> set[str]:
    fonts: Any = _resources(reader)["/Font"]
    return {str(f.get_object()["/BaseFont"]) for f in fonts.values()}


def test_a_new_certificate_uses_the_nile_format_and_renders_one_branded_page(world: World) -> None:  # noqa: F811
    """AC-1, AC-2, AC-3, AC-4: Letter landscape, one page, Inter embedded, the data on the page."""
    complete(world, "student", "video")
    assert attempt(world, "student", "q1", correct=5).json()["message"]["pass"] is True
    complete(world, "student", "lab")
    assert attempt(world, "student", "q2", correct=1).json()["message"]["pass"] is True
    assert request_certificate(world, "student").status_code == 200
    name = certificate_name(world, "student")

    assert _sql(f"select template from `tabLMS Certificate` where name = '{name}'") == [
        ["Nile Certificate"]
    ]
    pdf = open_link(world, "student", name)
    assert pdf.status_code == 200, pdf.text[:300]
    reader = PdfReader(io.BytesIO(pdf.content))
    assert len(reader.pages) == 1
    assert (
        round(float(reader.pages[0].mediabox.width)),
        round(float(reader.pages[0].mediabox.height)),
    ) == (
        792,
        612,
    )
    assert {"/Inter-Regular", "/Inter-SemiBold", "/Inter-Bold"} <= _fonts(reader)
    assert "/XObject" in _resources(reader)  # the inlined logo
    text = " ".join(reader.pages[0].extract_text().split())
    assert "Certificate of Completion" in text
    assert f"Nile pass rules {world.prefix}" in text
    assert f"Credential ID: {name}" in text
    link = f"https://{_site()}/courses/{world.course}/{name}"
    assert link in text.replace(" ", "")


def test_publishing_rules_are_unchanged_with_the_new_format(world: World) -> None:  # noqa: F811
    """AC-8: private for a guest, a student cannot publish, a Moderator can and the PDF opens."""
    name = certificate_name(world, "student")
    assert open_link(world, None, name).status_code == 403
    assert set_published(world, "student", name, 1).status_code == 403
    assert set_published(world, "admin", name, 1).status_code == 200
    guest = open_link(world, None, name)
    assert guest.status_code == 200 and guest.content.startswith(b"%PDF")
    assert set_published(world, "admin", name, 0).status_code == 200
