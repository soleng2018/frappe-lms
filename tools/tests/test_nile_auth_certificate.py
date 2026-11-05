"""Unit tests for nile_auth.certificate (spec 0010 AC-10) with a fake LMSCertificate base class."""

import importlib
import sys
import types
from collections.abc import Callable
from typing import Any

import pytest

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
