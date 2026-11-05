"""Unit tests for nile_tools.lms with a mock transport: no network (AC-7)."""

import json
from collections.abc import Callable

import httpx
import pytest

from nile_tools import lms
from nile_tools.lms import LmsError

SECRET = "s3cr3t-value"


def client(handler: Callable[[httpx.Request], httpx.Response]) -> lms.Lms:
    return lms.connect(
        "lms.test", "key1", SECRET, transport=httpx.MockTransport(handler), retry_wait=0
    )


def frappe_error(status: int, exc_type: str, message: str) -> httpx.Response:
    server = json.dumps([json.dumps({"message": message})])
    body = {
        "exc_type": exc_type,
        "exception": f"frappe.exceptions.{exc_type}: {message}",
        "_server_messages": server,
    }
    return httpx.Response(status, json=body)


def test_every_request_carries_the_token_and_goes_to_the_host() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    lms.list_records(client(handler), "LMS Course")
    assert seen[0].headers["Authorization"] == f"token key1:{SECRET}"
    assert seen[0].url.host == "lms.test"
    assert seen[0].url.raw_path.startswith(b"/api/resource/LMS%20Course?")
    assert seen[0].url.params["limit_page_length"] == "0"


def test_filters_and_fields_are_sent_as_json() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [{"name": "a"}]})

    out = lms.list_records(
        client(handler), "LMS Quiz", filters=[["nile_key", "=", "q"]], fields=["name"]
    )
    assert out == [{"name": "a"}]
    assert json.loads(seen[0].url.params["filters"]) == [["nile_key", "=", "q"]]
    assert json.loads(seen[0].url.params["fields"]) == ["name"]


def test_a_name_with_spaces_is_quoted_in_the_path() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"data": {"name": "0011 ch"}})

    lms.get_record(client(handler), "Course Chapter", "0011 ch/x")
    assert paths == ["/api/resource/Course%20Chapter/0011%20ch%2Fx"]


def test_reads_retry_on_a_5xx_then_succeed() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(502) if len(calls) < 3 else httpx.Response(200, json={"data": []})

    assert lms.list_records(client(handler), "LMS Course") == []
    assert len(calls) == 3


def test_reads_retry_on_a_connection_error_and_give_up_after_three() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("boom")

    with pytest.raises(LmsError, match=r"list LMS Course: GET https://lms.test.*ConnectError"):
        lms.list_records(client(handler), "LMS Course")
    assert len(calls) == 3


def test_a_4xx_read_is_not_retried() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return frappe_error(403, "PermissionError", "No permission")

    with pytest.raises(LmsError, match="HTTP 403, PermissionError: No permission"):
        lms.list_records(client(handler), "LMS Course")
    assert len(calls) == 1


@pytest.mark.parametrize("fail", [httpx.Response(500), httpx.ConnectError("x")])
def test_writes_are_never_retried(fail: httpx.Response | Exception) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if isinstance(fail, Exception):
            raise fail
        return fail

    with pytest.raises(LmsError):
        lms.update_record(client(handler), "LMS Course", "c", {"title": "x"})
    assert len(calls) == 1


def test_a_failed_write_names_the_record_url_status_type_and_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return frappe_error(417, "ValidationError", "<b>Title</b> is &amp; required")

    with pytest.raises(LmsError) as e:
        lms.create_record(
            client(handler), "Course Lesson", {"title": ""}, label="Course Lesson l-1"
        )
    text = str(e.value)
    assert text == (
        "Course Lesson l-1: POST https://lms.test/api/resource/Course%20Lesson -> HTTP 417, "
        "ValidationError: Title is & required"
    )
    assert SECRET not in text
    assert "Authorization" not in text
    assert "Traceback" not in text


def test_a_plain_text_error_body_is_still_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="Bad gateway")

    with pytest.raises(LmsError, match="HTTP 502, unknown: Bad gateway"):
        lms.update_record(client(handler), "LMS Course", "c", {})


def test_exc_type_is_taken_from_the_exception_text_when_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(417, json={"exception": "frappe.exceptions.MandatoryError: title"})

    with pytest.raises(LmsError, match="MandatoryError: title"):
        lms.update_record(client(handler), "LMS Course", "c", {})


def test_a_response_without_data_is_an_error_not_a_key_error() -> None:
    with pytest.raises(LmsError, match="sent no usable data"):
        lms.get_record(client(lambda r: httpx.Response(200, json={"oops": 1})), "LMS Course", "c")


def test_create_returns_the_record_with_its_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"title": "T", "nile_key": "k"}
        return httpx.Response(200, json={"data": {"name": "0001 T", "nile_key": "k"}})

    out = lms.create_record(client(handler), "Course Chapter", {"title": "T", "nile_key": "k"})
    assert out["name"] == "0001 T"


def test_a_duplicate_nile_key_fetches_the_record_by_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return frappe_error(
                417, "UniqueValidationError", "Duplicate entry 'k' for key 'nile_key'"
            )
        assert json.loads(request.url.params["filters"]) == [["nile_key", "=", "k"]]
        return httpx.Response(200, json={"data": [{"name": "saved", "nile_key": "k"}]})

    out = lms.create_record(client(handler), "Course Chapter", {"title": "T", "nile_key": "k"})
    assert out["name"] == "saved"


def test_a_duplicate_on_another_key_is_still_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return frappe_error(409, "DuplicateEntryError", "Duplicate entry 'x' for key 'PRIMARY'")

    with pytest.raises(LmsError, match="HTTP 409"):
        lms.create_record(client(handler), "Course Chapter", {"title": "T", "nile_key": "k"})


def test_a_duplicate_with_no_record_to_fetch_is_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return frappe_error(417, "UniqueValidationError", "for key 'nile_key'")
        return httpx.Response(200, json={"data": []})

    with pytest.raises(LmsError, match="UniqueValidationError"):
        lms.create_record(client(handler), "Course Chapter", {"title": "T", "nile_key": "k"})


def test_update_sends_only_what_it_is_given() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert json.loads(request.content) == {"title": "New"}
        return httpx.Response(200, json={"data": {"name": "c", "title": "New"}})

    assert lms.update_record(client(handler), "LMS Course", "c", {"title": "New"})["title"] == "New"


def test_logged_user_returns_the_name_the_token_signs_in_as() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"message": "svc@example.com"})

    assert lms.logged_user(client(handler)) == "svc@example.com"
    assert seen[0].url.path == "/api/method/frappe.auth.get_logged_user"
    assert seen[0].headers["Authorization"] == f"token key1:{SECRET}"


def test_logged_user_names_the_url_when_the_answer_has_no_message() -> None:
    with pytest.raises(LmsError, match=r"logged in user: GET .*get_logged_user sent no message"):
        lms.logged_user(client(lambda r: httpx.Response(200, json={"data": 1})))


def test_logged_user_names_the_status_when_frappe_refuses_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return frappe_error(401, "AuthenticationError", "Invalid token")

    with pytest.raises(LmsError, match=r"HTTP 401.*AuthenticationError") as e:
        lms.logged_user(client(handler))
    assert SECRET not in str(e.value)
