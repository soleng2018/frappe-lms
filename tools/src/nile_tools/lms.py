"""A thin client for the Frappe REST API of the LMS: list, get, create, update."""

import html
import json
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

__all__ = [
    "Lms",
    "LmsError",
    "connect",
    "create_record",
    "get_record",
    "list_records",
    "update_record",
]

READ_TRIES = 3
_DUPLICATE_STATUSES = (409, 417)
_TAGS = re.compile(r"<[^>]+>")

Record = dict[str, Any]


class LmsError(Exception):
    """A request to the LMS failed. The message names the record, URL, status and reason."""


@dataclass(frozen=True)
class Lms:
    """An open connection: the http client holds the token header, so nothing else sees it."""

    http: httpx.Client
    retry_wait: float = 1.0


def connect(
    host: str,
    api_key: str,
    api_secret: str,
    *,
    transport: httpx.BaseTransport | None = None,
    retry_wait: float = 1.0,
) -> Lms:
    """Open a connection to `https://<host>` that signs every request with the API token."""
    http = httpx.Client(
        base_url=f"https://{host}",
        headers={"Authorization": f"token {api_key}:{api_secret}"},
        timeout=30,
        transport=transport,
    )
    return Lms(http, retry_wait)


def _server_message(body: Mapping[str, Any]) -> str:
    raw = body.get("_server_messages")
    if isinstance(raw, str):
        try:
            texts = [json.loads(m).get("message", "") for m in json.loads(raw)]
        except (ValueError, AttributeError, TypeError):
            texts = []
        text = " ".join(t for t in texts if t)
        if text:
            return html.unescape(_TAGS.sub("", text)).strip()
    exception = body.get("exception")
    if isinstance(exception, str) and exception:
        return exception.split(": ", 1)[-1].strip()
    return ""


def _failure(r: httpx.Response) -> tuple[str, str]:
    """Return Frappe's `exc_type` and its decoded message for a failed response."""
    try:
        body = r.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return "unknown", r.text[:200].strip()
    exception = body.get("exception")
    exc_type = body.get("exc_type") or (
        exception.split(":", 1)[0].rsplit(".", 1)[-1] if isinstance(exception, str) else ""
    )
    return str(exc_type or "unknown"), _server_message(body) or r.text[:200].strip()


def _describe(label: str, r: httpx.Response) -> str:
    exc_type, message = _failure(r)
    where = f"{r.request.method} {r.request.url} -> HTTP {r.status_code}"
    return f"{label}: {where}, {exc_type}: {message}"


def _send(lms: Lms, label: str, method: str, path: str, **kwargs: Any) -> httpx.Response:
    tries = READ_TRIES if method == "GET" else 1  # a repeated write could duplicate
    for attempt in range(1, tries + 1):
        try:
            r = lms.http.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            if attempt < tries:
                time.sleep(lms.retry_wait)
                continue
            raise LmsError(
                f"{label}: {method} {lms.http.base_url.join(path)} failed: {type(e).__name__}"
            ) from None
        if r.status_code >= 500 and attempt < tries:
            time.sleep(lms.retry_wait)
            continue
        if r.is_success:
            return r
        raise LmsError(_describe(label, r))
    raise AssertionError("unreachable")  # pragma: no cover


def _data(label: str, r: httpx.Response) -> Any:
    try:
        return r.json()["data"]
    except (ValueError, KeyError, TypeError):
        raise LmsError(f"{label}: {r.request.method} {r.request.url} sent no usable data") from None


def _path(doctype: str, name: str | None = None) -> str:
    base = f"/api/resource/{quote(doctype, safe='')}"
    return base if name is None else f"{base}/{quote(name, safe='')}"


def list_records(
    lms: Lms,
    doctype: str,
    *,
    filters: Sequence[Sequence[object]] = (),
    fields: Sequence[str] = ("*",),
) -> list[Record]:
    """List every record of a type matching the filters, all fields unless named."""
    params = {
        "fields": json.dumps(list(fields)),
        "filters": json.dumps(list(filters)),
        "limit_page_length": "0",
    }
    r = _send(lms, f"list {doctype}", "GET", _path(doctype), params=params)
    return list(_data(f"list {doctype}", r))


def get_record(lms: Lms, doctype: str, name: str) -> Record:
    """Fetch one record with its child tables."""
    label = f"{doctype} {name}"
    return dict(_data(label, _send(lms, label, "GET", _path(doctype, name))))


def update_record(
    lms: Lms, doctype: str, name: str, changes: Mapping[str, object], *, label: str = ""
) -> Record:
    """Write the changed fields of one record; a child table must be sent whole."""
    label = label or f"{doctype} {name}"
    r = _send(lms, label, "PUT", _path(doctype, name), json=dict(changes))
    return dict(_data(label, r))


def create_record(lms: Lms, doctype: str, data: Mapping[str, object], *, label: str = "") -> Record:
    """Create a record. A duplicate `nile_key` means an earlier try saved it, so fetch that one."""
    label = label or f"{doctype} {data.get('nile_key', '')}".strip()
    try:
        r = _send(lms, label, "POST", _path(doctype), json=dict(data))
    except LmsError as e:
        key = data.get("nile_key")
        if key and _is_duplicate_key(str(e)):
            found = list_records(lms, doctype, filters=[["nile_key", "=", key]])
            if found:
                return found[0]
        raise
    return dict(_data(label, r))


def _is_duplicate_key(message: str) -> bool:
    return any(f"HTTP {s}" in message for s in _DUPLICATE_STATUSES) and "nile_key" in message
