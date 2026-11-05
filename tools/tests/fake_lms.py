"""An in-memory stand-in for the Frappe REST API, for sync tests that must not touch a network."""

import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote

import httpx

from nile_tools import lms

RICH = {"description", "question"}


class FakeLms:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, dict[str, Any]]] = {}
        self.writes: list[tuple[str, str, str]] = []  # method, doctype, name
        self.fail_write: Callable[[int, str, str], httpx.Response | None] = lambda n, m, d: None
        self.counter = 0
        self.password_denied = False
        self.seed("LMS Settings", "LMS Settings", allow_guest_access=1)
        # The single System Settings record, as a fresh site holds it.
        self.seed(
            "System Settings",
            "System Settings",
            language="en",
            disable_user_pass_login=0,
            login_with_email_link=1,
        )

    def client(self) -> lms.Lms:
        return lms.connect(
            "lms.test", "k", "s", transport=httpx.MockTransport(self.handle), retry_wait=0
        )

    def seed(self, doctype: str, name: str, **fields: Any) -> dict[str, Any]:
        doc = {"name": name, "doctype": doctype, **fields}
        self.docs.setdefault(doctype, {})[name] = doc
        return doc

    def of(self, doctype: str) -> dict[str, dict[str, Any]]:
        return self.docs.get(doctype, {})

    def by_key(self, doctype: str, key: str) -> dict[str, Any]:
        return next(d for d in self.of(doctype).values() if d.get("nile_key") == key)

    def _name(self, doctype: str, data: dict[str, Any]) -> str:
        self.counter += 1
        if doctype == "LMS Quiz":
            slug = re.sub(r"\W+", "-", data["title"].lower()).strip("-")
            return slug if slug not in self.of(doctype) else f"{slug}-2"
        if doctype == "Social Login Key":  # Frappe names it after the provider
            return re.sub(r"\W+", "_", data["provider_name"].lower())
        return f"{doctype[:3]}-{self.counter:04d}"

    @staticmethod
    def _masked(doc: dict[str, Any]) -> dict[str, Any]:
        """Frappe returns a password field as stars."""
        return {**doc, "client_secret": "*****"} if "client_secret" in doc else doc

    @staticmethod
    def _matches(doc: dict[str, Any], filters: list[list[Any]]) -> bool:
        for field, op, value in filters:
            have = doc.get(field)
            if (op == "=" and have != value) or (op == "in" and have not in value):
                return False
        return True

    def handle(self, request: httpx.Request) -> httpx.Response:
        parts = [unquote(p) for p in request.url.raw_path.decode().split("?")[0].split("/")]
        doctype = parts[3]
        name = parts[4] if len(parts) > 4 else None
        store = self.docs.setdefault(doctype, {})
        if parts[2] == "method" and doctype == "frappe.client.get_password":
            if self.password_denied:
                return httpx.Response(403, json={"exc_type": "PermissionError"})
            asked = request.url.params
            doc = self.docs.get(asked["doctype"], {}).get(asked["name"], {})
            return httpx.Response(200, json={"message": doc.get(asked["fieldname"])})
        if request.method == "GET":
            if name:
                return (
                    httpx.Response(200, json={"data": self._masked(store[name])})
                    if name in store
                    else httpx.Response(404, json={"exc_type": "DoesNotExistError"})
                )
            filters = json.loads(request.url.params.get("filters", "[]"))
            rows = [
                {k: v for k, v in d.items() if not isinstance(v, list)}
                for d in store.values()
                if self._matches(d, filters)
            ]
            return httpx.Response(200, json={"data": rows})
        self.counter_writes = len(self.writes) + 1
        refused = self.fail_write(self.counter_writes, request.method, doctype)
        if refused is not None:
            return refused
        if request.method == "DELETE":
            store.pop(name or "")
            self.writes.append(("DELETE", doctype, name or ""))
            return httpx.Response(202, json={"message": "ok"})
        body = json.loads(request.content)
        for f in RICH & body.keys():
            text = str(body[f])
            # Frappe v16 sanitize_html leaves a value alone unless it holds an HTML tag.
            body[f] = text.replace("&", "&amp;") if "<" in text or ">" in text else text
        if request.method == "POST":
            key = body.get("nile_key")
            if key and any(d.get("nile_key") == key for d in store.values()):
                msg = f"Duplicate entry '{key}' for key 'nile_key'"
                return httpx.Response(
                    417,
                    json={
                        "exc_type": "UniqueValidationError",
                        "exception": f"frappe.exceptions.UniqueValidationError: {msg}",
                    },
                )
            new = {"doctype": doctype, "name": self._name(doctype, body), **body}
            if doctype == "Course Lesson":
                new["course"] = self.docs["Course Chapter"][body["chapter"]]["course"]
            store[new["name"]] = new
            self.writes.append(("POST", doctype, new["name"]))
            return httpx.Response(200, json={"data": new})
        store[name or ""].update(body)
        self.writes.append(("PUT", doctype, name or ""))
        return httpx.Response(200, json={"data": store[name or ""]})
