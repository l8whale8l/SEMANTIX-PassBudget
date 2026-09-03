"""The two ceilings that only exist over HTTP.

Everything about the *scenario* is bounded in the domain, where every entry point reaches it
(`tests/unit/test_input_limits.py`). Two things have no domain representation and are bounded
here instead: the size of the request body the server agrees to read, and the size of a profile
revision's free-form payload.

The body ceiling is checked before parsing, so an oversized request must never reach the
application service at all -- that is the point of a resource-exhaustion bound, and it is
asserted rather than assumed. It is bounded by *received* bytes as well as by the declared
`Content-Length`, because a chunked request declares nothing;
`tests/unit/test_body_limit.py` drives that at the ASGI layer, where the stopping is visible.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, NoReturn

import pytest
from fastapi.testclient import TestClient

from semantix_passbudget.domain import limits
from semantix_passbudget.domain.canonical import canonical_bytes
from semantix_passbudget.interfaces.api import app as app_module
from semantix_passbudget.interfaces.api.app import app


def _client() -> TestClient:
    return TestClient(app)


def _sized_note(canonical_length: int) -> str:
    """A `{"note": ...}` payload whose canonical encoding is exactly `canonical_length` bytes."""
    overhead = len(canonical_bytes({"note": ""}))
    return "x" * (canonical_length - overhead)


def test_a_body_over_the_ceiling_is_refused_before_the_service_sees_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise AssertionError("an oversized request reached the application service")

    monkeypatch.setattr(app_module.service, "run", boom)
    oversized = b'{"fixture": "' + b"A" * (limits.MAX_REQUEST_BODY_BYTES + 1) + b'"}'
    response = _client().post(
        "/api/v1/runs", content=oversized, headers={"content-type": "application/json"}
    )
    assert response.status_code == 413
    body = response.json()["error"]
    assert body["code"] == "INPUT_LIMIT_EXCEEDED"
    assert body["details"]["limit_name"] == "request body size"
    assert body["details"]["limit_maximum"] == str(limits.MAX_REQUEST_BODY_BYTES)


def test_a_body_under_the_ceiling_is_still_parsed_and_judged_on_its_content() -> None:
    """The ceiling must not swallow ordinary requests: this one is rejected on its content."""
    response = _client().post("/api/v1/runs", json={"fixture": "PB-GOLDEN-NOPE-99"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FIXTURE_NOT_FOUND"


def _chunked(total: int, chunk: int = 64 * 1024) -> Iterator[bytes]:
    """A JSON body streamed with no `Content-Length`, so only received bytes can bound it."""
    head = b'{"fixture": "'
    yield head
    sent = len(head)
    filler = b"A" * chunk
    while sent < total:
        yield filler
        sent += chunk
    yield b'"}'


def test_a_chunked_body_over_the_ceiling_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: this reached the router and returned 422 FIXTURE_NOT_FOUND.

    Nothing declared a length, so a `Content-Length` check saw nothing to check and the whole
    9 MiB was assembled in memory and parsed before anything objected.
    """

    def boom(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise AssertionError("an oversized chunked request reached the application service")

    monkeypatch.setattr(app_module.service, "run", boom)
    response = _client().post(
        "/api/v1/runs",
        content=_chunked(limits.MAX_REQUEST_BODY_BYTES + 1024 * 1024),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    body = response.json()["error"]
    assert body["code"] == "INPUT_LIMIT_EXCEEDED"
    assert body["details"]["limit_measured"] == "received"


def test_a_chunked_body_under_the_ceiling_is_processed_normally() -> None:
    response = _client().post(
        "/api/v1/runs",
        content=iter([b'{"fixture": "PB-GOLDEN-QUEUE-01"}']),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["run_id"]


def test_an_oversized_profile_revision_payload_is_refused() -> None:
    client = _client()
    profile = client.post(
        "/api/v1/profiles",
        json={
            "stable_key": "LIMIT-PROBE-GS-01",
            "kind": "GROUND_STATION",
            "name": "Limit probe",
        },
    )
    assert profile.status_code == 201
    profile_id = profile.json()["profile_id"]

    payload = {"note": _sized_note(limits.MAX_PROFILE_REVISION_PAYLOAD_BYTES + 1)}
    assert len(canonical_bytes(payload)) == limits.MAX_PROFILE_REVISION_PAYLOAD_BYTES + 1
    filler = str(payload["note"])
    response = client.post(
        f"/api/v1/profiles/{profile_id}/revisions",
        json={"label": "oversized", "payload": payload},
    )
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "INPUT_LIMIT_EXCEEDED"
    assert body["details"]["limit_name"] == "profile revision payload size"
    assert filler not in response.text


def test_a_profile_revision_payload_inside_the_ceiling_is_accepted() -> None:
    client = _client()
    profile = client.post(
        "/api/v1/profiles",
        json={
            "stable_key": "LIMIT-PROBE-GS-02",
            "kind": "GROUND_STATION",
            "name": "Limit probe ok",
        },
    )
    profile_id = profile.json()["profile_id"]
    # Exactly on the boundary in canonical bytes, which is the unit the ceiling is measured in.
    payload = {"note": _sized_note(limits.MAX_PROFILE_REVISION_PAYLOAD_BYTES)}
    assert len(canonical_bytes(payload)) == limits.MAX_PROFILE_REVISION_PAYLOAD_BYTES
    response = client.post(
        f"/api/v1/profiles/{profile_id}/revisions",
        json={"label": "sized", "payload": payload},
    )
    assert response.status_code == 201, response.json()
