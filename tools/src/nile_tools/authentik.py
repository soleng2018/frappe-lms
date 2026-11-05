"""A small client for the Authentik REST API. Errors name the URL and never carry the token."""

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

__all__ = [
    "Authentik",
    "AuthentikError",
    "connect",
    "create",
    "delete",
    "find",
    "get",
    "get_one",
    "set_password",
    "update",
]

Record = dict[str, Any]


class AuthentikError(Exception):
    """A request to Authentik failed. The message names the URL, the status and the field errors."""


@dataclass(frozen=True)
class Authentik:
    """An open connection: the http client holds the bearer header, so nothing else sees it."""

    http: httpx.Client
    tries: int = 60  # with the 5 second step, a 5 minute window
    retry_wait: float = 5.0


def connect(
    host: str,
    token: str,
    *,
    transport: httpx.BaseTransport | None = None,
    tries: int = 60,
    retry_wait: float = 5.0,
) -> Authentik:
    """Open a connection to `https://<host>/api/v3` that signs every request with the token."""
    http = httpx.Client(
        base_url=f"https://{host}/api/v3/",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
        transport=transport,
    )
    return Authentik(http, tries, retry_wait)


def _call(ak: Authentik, method: str, path: str, **kwargs: Any) -> httpx.Response:
    path = path.lstrip("/")  # a leading slash would drop the /api/v3/ part of the base URL
    url = ak.http.base_url.join(path)
    tries = 1 if method == "POST" else ak.tries  # a repeated create could duplicate
    for attempt in range(1, tries + 1):
        try:
            r = ak.http.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            if attempt < tries:
                time.sleep(ak.retry_wait)
                continue
            raise AuthentikError(f"{method} {url} failed: {type(e).__name__}") from None
        if r.status_code >= 500 and attempt < tries:
            time.sleep(ak.retry_wait)
            continue
        break
    if r.is_success:
        return r
    try:
        detail = json.dumps(r.json())[:300]
    except ValueError:
        detail = r.text[:200].strip()
    raise AuthentikError(f"{method} {url} -> HTTP {r.status_code}: {detail}")


def find(ak: Authentik, path: str, **params: str) -> list[Record]:
    """Return every item of a list endpoint matching the exact query parameters."""
    r = _call(ak, "GET", path, params={"page_size": "100", **params})
    return list(r.json()["results"])


def get(ak: Authentik, path: str, **params: str) -> Record:
    """Return the JSON object at a detail path."""
    return dict(_call(ak, "GET", path, params=params).json())


def get_one(ak: Authentik, path: str, **params: str) -> Record | None:
    """Return the single match for a query, None if there is none, an error if there are many."""
    # Some list endpoints ignore a filter they do not know, so keep exact matches client side.
    found = [
        r for r in find(ak, path, **params) if all(r.get(k, v) == v for k, v in params.items())
    ]
    if len(found) > 1:
        raise AuthentikError(f"{ak.http.base_url.join(path)} {params} matched {len(found)} items")
    return found[0] if found else None


def create(ak: Authentik, path: str, body: Mapping[str, object]) -> Record:
    """Create one item; a create is never retried here, the caller reads by name first."""
    return dict(_call(ak, "POST", path, json=dict(body)).json())


def update(ak: Authentik, path: str, body: Mapping[str, object]) -> Record:
    """Write the given fields of one item."""
    return dict(_call(ak, "PATCH", path, json=dict(body)).json())


def delete(ak: Authentik, path: str) -> None:
    """Delete one item."""
    _call(ak, "DELETE", path)


def set_password(ak: Authentik, user_pk: int | str, password: str) -> None:
    """Set a user's password; the answer has no body."""
    _call(ak, "POST", f"/core/users/{user_pk}/set_password/", json={"password": password})
