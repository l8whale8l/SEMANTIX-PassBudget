"""The request-body ceiling, driven at the ASGI layer where the property is actually visible.

`TestClient` delivers a request body as a single `http.request` message however the caller
streamed it, so an integration test can prove the *status* but not the *stopping*. These cases
drive `RequestBodySizeLimit` directly with a `receive` that hands over one chunk at a time and
counts how many were pulled, which is the only way to show that an oversized body is refused
during receipt rather than after it has been assembled in memory.
"""

from __future__ import annotations

import json
from typing import Any

import anyio

from semantix_passbudget.interfaces.api.body_limit import RequestBodySizeLimit

CEILING = 1_000
CHUNK = 100


def _scope(headers: list[tuple[bytes, bytes]] | None = None) -> dict[str, Any]:
    return {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/runs",
        "headers": headers or [(b"content-type", b"application/json")],
    }


class _Harness:
    """A downstream app that drains the body, plus the instrumentation around it."""

    def __init__(self, chunks: int, *, chunk_size: int = CHUNK) -> None:
        self.chunks = chunks
        self.chunk_size = chunk_size
        self.pulled = 0
        self.sent: list[dict[str, Any]] = []
        self.body_seen = 0
        self.downstream_finished = False

    async def receive(self) -> dict[str, Any]:
        if self.pulled >= self.chunks:
            return {"type": "http.request", "body": b"", "more_body": False}
        self.pulled += 1
        return {
            "type": "http.request",
            "body": b"x" * self.chunk_size,
            "more_body": self.pulled < self.chunks,
        }

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)

    async def app(self, scope: Any, receive: Any, send: Any) -> None:
        while True:
            message = await receive()
            self.body_seen += len(message.get("body", b""))
            if not message.get("more_body", False):
                break
        self.downstream_finished = True
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    def status(self) -> int:
        return int(self.sent[0]["status"])

    def error(self) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads(self.sent[1]["body"])
        return dict(payload["error"])


def _run(harness: _Harness, headers: list[tuple[bytes, bytes]] | None = None) -> None:
    middleware = RequestBodySizeLimit(harness.app, maximum=CEILING)
    anyio.run(middleware, _scope(headers), harness.receive, harness.send)


def test_an_oversized_stream_is_stopped_during_receipt_not_after_assembly() -> None:
    """Twenty times the ceiling is offered; it must not pull twenty times the ceiling."""
    harness = _Harness(chunks=200)  # 20,000 bytes against a 1,000 byte ceiling
    _run(harness)

    assert harness.status() == 413
    assert harness.error()["code"] == "INPUT_LIMIT_EXCEEDED"
    assert harness.error()["details"]["limit_measured"] == "received"
    # The decisive assertion: it stopped at the first chunk that crossed the line.
    assert harness.pulled == CEILING // CHUNK + 1 == 11
    assert harness.body_seen <= CEILING + CHUNK
    assert not harness.downstream_finished


def test_a_body_under_the_ceiling_reaches_the_application_whole() -> None:
    harness = _Harness(chunks=9)  # 900 bytes
    _run(harness)

    assert harness.downstream_finished
    assert harness.body_seen == 900
    assert harness.status() == 201


def test_the_boundary_byte_count_is_accepted() -> None:
    harness = _Harness(chunks=CEILING // CHUNK)  # exactly 1,000 bytes
    _run(harness)

    assert harness.downstream_finished
    assert harness.body_seen == CEILING
    assert harness.status() == 201


def test_one_byte_over_the_boundary_is_refused() -> None:
    over = _Harness(chunks=1, chunk_size=CEILING + 1)
    _run(over)
    assert over.status() == 413
    assert over.error()["details"]["limit_actual"] == str(CEILING + 1)


def test_a_declared_length_over_the_ceiling_is_refused_without_reading_the_body() -> None:
    harness = _Harness(chunks=200)
    _run(harness, headers=[(b"content-length", str(20 * CEILING).encode())])

    assert harness.status() == 413
    assert harness.error()["details"]["limit_measured"] == "declared"
    assert harness.pulled == 0, "a declared oversize costs nothing but the headers"


def test_a_body_larger_than_its_declared_length_is_still_refused() -> None:
    """The header is advisory. A caller that understates it must not thereby raise the ceiling."""
    harness = _Harness(chunks=200)
    _run(harness, headers=[(b"content-length", b"10")])

    assert harness.status() == 413
    assert harness.error()["details"]["limit_measured"] == "received"
    assert harness.pulled == CEILING // CHUNK + 1


def test_a_non_http_scope_is_passed_through_untouched() -> None:
    harness = _Harness(chunks=1)
    middleware = RequestBodySizeLimit(harness.app, maximum=CEILING)
    scope = {"type": "lifespan"}
    anyio.run(middleware, scope, harness.receive, harness.send)
    assert harness.downstream_finished
