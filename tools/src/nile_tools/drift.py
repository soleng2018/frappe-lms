"""Compare the records git would write with the records the LMS holds (`sync --check`)."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

__all__ = ["Difference", "Drift", "Record", "compare"]


@dataclass(frozen=True)
class Record:
    """One LMS record as a plain value. `key` is its nile_key, None if made in the LMS."""

    doctype: str
    key: str | None
    fields: Mapping[str, object]
    name: str | None = None


@dataclass(frozen=True)
class Difference:
    """One field where the LMS holds something other than what git would write."""

    doctype: str
    key: str
    field: str
    wanted: object
    found: object


@dataclass(frozen=True)
class Drift:
    """Edits made in the LMS to synced records, and LMS records the sync does not manage."""

    differences: tuple[Difference, ...]
    unmanaged: tuple[Record, ...]


def _same(wanted: object, found: object) -> bool:
    # The API returns an unset field as None or an empty string.
    empty = (None, "")
    return (wanted in empty and found in empty) or wanted == found


def compare(wanted: Iterable[Record], found: Iterable[Record]) -> Drift:
    """List every wanted field the LMS holds differently, and every LMS record with no key.

    Only fields git writes are compared, so fields LMS fills itself never count as drift.
    A wanted record that does not exist yet is a create, not drift.
    """
    found = tuple(found)  # read twice below, so a generator must not be spent by the first pass
    in_lms = {(r.doctype, r.key): r for r in found if r.key}
    differences = tuple(
        Difference(w.doctype, w.key, field, value, current.fields.get(field))
        for w in wanted
        if w.key and (current := in_lms.get((w.doctype, w.key)))
        for field, value in w.fields.items()
        if not _same(value, current.fields.get(field))
    )
    return Drift(differences, tuple(r for r in found if not r.key))
