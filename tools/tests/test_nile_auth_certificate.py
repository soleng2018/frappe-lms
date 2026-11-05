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


@pytest.fixture
def make(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Any]:
    """Build a certificate object from the real subclass over the fake base."""
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
