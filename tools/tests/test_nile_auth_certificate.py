"""Unit tests for nile_auth.certificate (spec 0010 AC-10) with a fake LMSCertificate base class."""

import ast
import importlib
import re
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]

BASE = "lms.lms.doctype.lms_certificate.lms_certificate"


class FakeBase:
    """Records which checks ran. Subclasses set `new` and `changed`."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.new = True
        self.changed: set[str] = set()
        self.batch_name = ""
        self.course = "c1"

    def is_new(self) -> bool:
        return self.new

    def has_value_changed(self, field: str) -> bool:
        return field in self.changed

    def validate_role_of_owner(self) -> None:
        self.calls.append("role")

    def validate_batch_enrollment(self) -> None:
        self.calls.append("batch")

    def validate_course_enrollment(self) -> None:
        self.calls.append("course")


class FakeFrappeError(Exception):
    """Stands in for the exception frappe.throw raises."""


def _fake_frappe(monkeypatch: pytest.MonkeyPatch, app_dir: Path | None = None) -> None:
    """A minimal frappe: throw raises, get_app_path points into `app_dir` when given."""
    frappe = types.ModuleType("frappe")

    def throw(message: str) -> None:
        raise FakeFrappeError(message)

    def get_app_path(app: str, *parts: str) -> str:
        return str((app_dir or ROOT / "apps" / "nile_auth" / "nile_auth").joinpath(*parts))

    frappe.throw = throw  # type: ignore[attr-defined]
    frappe.get_app_path = get_app_path  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "frappe", frappe)


@pytest.fixture
def make(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Any]:
    """Build a certificate object from the real subclass over the fake base."""
    _fake_frappe(monkeypatch)
    for name in ("lms", "lms.lms", "lms.lms.doctype", "lms.lms.doctype.lms_certificate"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    base = types.ModuleType(BASE)
    base.LMSCertificate = FakeBase  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, BASE, base)
    monkeypatch.delitem(sys.modules, "nile_auth.certificate", raising=False)
    cls = importlib.import_module("nile_auth.certificate").NileLMSCertificate

    def _make(*, new: bool, changed: tuple[str, ...] = (), batch: str = "") -> Any:
        doc = cls()
        doc.new, doc.changed, doc.batch_name = new, set(changed), batch
        return doc

    return _make


def test_a_new_certificate_runs_the_course_checks(make: Callable[..., Any]) -> None:
    doc = make(new=True)
    doc.validate_criteria()
    assert doc.calls == ["role", "course"]


def test_a_new_batch_certificate_runs_the_batch_checks(make: Callable[..., Any]) -> None:
    doc = make(new=True, batch="b1")
    doc.validate_criteria()
    assert doc.calls == ["role", "batch"]


def test_a_saved_certificate_with_the_same_identity_skips_enrollment_checks(
    make: Callable[..., Any],
) -> None:
    doc = make(new=False)
    doc.validate_criteria()
    assert doc.calls == ["role"]


@pytest.mark.parametrize("field", ["member", "course", "batch_name"])
def test_a_saved_certificate_that_is_moved_runs_the_checks(
    make: Callable[..., Any], field: str
) -> None:
    doc = make(new=False, changed=(field,))
    doc.validate_criteria()
    assert doc.calls == ["role", "course"]


def test_a_moved_saved_batch_certificate_runs_the_batch_checks(make: Callable[..., Any]) -> None:
    doc = make(new=False, changed=("member",), batch="b1")
    doc.validate_criteria()
    assert doc.calls == ["role", "batch"]


def test_the_hook_points_at_the_class_that_exists() -> None:
    """AC-10: a typo in hooks.py would silently turn the override off."""
    app = ROOT / "apps/nile_auth/nile_auth"
    tree = ast.parse((app / "hooks.py").read_text())
    value = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", "") == "override_doctype_class" for t in node.targets)
    )
    assert list(value) == ["LMS Certificate"]
    module, _, cls = value["LMS Certificate"].rpartition(".")
    assert module == "nile_auth.certificate"
    classes = {
        n.name
        for n in ast.parse((app / "certificate.py").read_text()).body
        if isinstance(n, ast.ClassDef)
    }
    assert cls in classes


def test_the_app_version_and_the_image_pin_move_together() -> None:
    """AC-10: nile_auth is copied into the image, so both numbers must change in one commit."""
    pyproject = (ROOT / "apps/nile_auth/pyproject.toml").read_text()
    env = (ROOT / "deploy/versions.env").read_text()
    app = re.search(r'^version = "([^"]+)"', pyproject, re.M)
    pin = re.search(r"^BUILD_NILE_AUTH_VERSION=(\S+)", env, re.M)
    assert app and pin
    assert app.group(1) == pin.group(1)


def _certificate_module(monkeypatch: pytest.MonkeyPatch, app_dir: Path) -> Any:
    make_fixture_base = types.ModuleType(BASE)
    make_fixture_base.LMSCertificate = FakeBase  # type: ignore[attr-defined]
    for name in ("lms", "lms.lms", "lms.lms.doctype", "lms.lms.doctype.lms_certificate"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, BASE, make_fixture_base)
    _fake_frappe(monkeypatch, app_dir)
    monkeypatch.delitem(sys.modules, "nile_auth.certificate", raising=False)
    return importlib.import_module("nile_auth.certificate")


def test_logo_data_uri_inlines_an_allowed_brand_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Spec 0012 AC-4: the logo is read from the app and inlined, so a render fetches nothing."""
    images = tmp_path / "public" / "images"
    images.mkdir(parents=True)
    (images / "nile-logo.png").write_bytes(b"\x89PNGdata")
    uri = _certificate_module(monkeypatch, tmp_path).logo_data_uri("nile-logo.png")
    assert uri == "data:image/png;base64,iVBOR2RhdGE="


def test_logo_data_uri_refuses_other_files_and_names_a_missing_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _certificate_module(monkeypatch, tmp_path)
    with pytest.raises(FakeFrappeError, match="not one of"):
        module.logo_data_uri("../../etc/passwd")
    with pytest.raises(FakeFrappeError, match="missing from the image"):
        module.logo_data_uri("nile-logo.png")
