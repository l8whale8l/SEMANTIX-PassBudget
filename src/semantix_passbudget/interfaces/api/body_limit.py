"""Refuse an oversized request body by what actually arrives, not by what it claims.

A `Content-Length` check is the cheap half of the job and it is worth keeping: it refuses before a
single byte of body is read. It is not the whole job, because the header is optional and
advisory. A chunked request carries no `Content-Length` at all, and a request that declares one is
under no obligation to send that many bytes -- so a ceiling that trusts the header is a ceiling a
caller can decline to be bound by.

This middleware therefore counts the body as it is received, at the ASGI layer, and stops the
moment the running total passes the limit. Stopping *during* receive is the point: buffering the
whole oversized body and then measuring it would spend exactly the memory the ceiling exists to
protect.

It is a plain ASGI middleware rather than a `BaseHTTPMiddleware`, because only at this layer can
the `receive` callable be wrapped; `BaseHTTPMiddleware` hands the handler an already-assembled
`Request`.
"""

from __future__ import annotations

import json
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _BodyTooLarge(BaseException):
    """Raised out of the wrapped `receive` once the running total passes the limit.

    Deliberately a `BaseException`. FastAPI wraps body parsing in a bare `except Exception` and
    turns anything it catches into `400 There was an error parsing the body`, which would hide
    the ceiling behind a generic parse failure and report the wrong status. This is control flow
    that no generic handler may swallow -- the same reason `asyncio.CancelledError` is a
    `BaseException` -- and the one frame that must see it catches it by name.
    """

    def __init__(self, received: int) -> None:
        super().__init__(received)
        self.received = received


def _body_too_large(error: BaseException) -> _BodyTooLarge | None:
    """Find the signal, including inside a task group's `BaseExceptionGroup`."""
    if isinstance(error, _BodyTooLarge):
        return error
    if isinstance(error, BaseExceptionGroup):
        for nested in error.exceptions:
            found = _body_too_large(nested)
            if found is not None:
                return found
    return None


def _payload(actual: int, maximum: int, measured: str) -> bytes:
    return json.dumps(
        {
            "error": {
                "code": "INPUT_LIMIT_EXCEEDED",
                "message": (
                    f"Request body exceeds the P0 input ceiling: {actual} bytes {measured} "
                    f"against a maximum of {maximum}. The request is refused whole."
                ),
                "scope": "request",
                "field_paths": [],
                "affected_branches": [],
                "details": {
                    "limit_name": "request body size",
                    "limit_maximum": str(maximum),
                    "limit_actual": str(actual),
                    "limit_unit": "bytes",
                    "limit_measured": measured,
                },
            }
        },
        ensure_ascii=False,
    ).encode("utf-8")


class RequestBodySizeLimit:
    """Bound the request body both by its declared length and by its received length."""

    def __init__(self, app: ASGIApp, *, maximum: int) -> None:
        self.app = app
        self.maximum = maximum

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = self._declared_length(scope)
        if declared is not None and declared > self.maximum:
            # Nothing has been read yet, so this costs nothing but the headers.
            await self._refuse(send, declared, "declared")
            return

        state: dict[str, Any] = {"received": 0, "started": False}

        async def limited_receive() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                state["received"] += len(message.get("body", b"") or b"")
                if state["received"] > self.maximum:
                    raise _BodyTooLarge(state["received"])
            return message

        async def watched_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                state["started"] = True
            await send(message)

        try:
            await self.app(scope, limited_receive, watched_send)
        except BaseException as error:
            exceeded = _body_too_large(error)
            if exceeded is None or state["started"]:
                # Not ours, or the handler already committed a status line: a second status line
                # would corrupt the response, so let it surface rather than write over the wire.
                raise
            await self._refuse(send, exceeded.received, "received")

    def _declared_length(self, scope: Scope) -> int | None:
        for name, value in scope.get("headers", ()):
            if name == b"content-length":
                text = value.decode("latin-1").strip()
                return int(text) if text.isdigit() else None
        return None

    async def _refuse(self, send: Send, actual: int, measured: str) -> None:
        body = _payload(actual, self.maximum, measured)
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                    # The caller must not keep streaming into a connection we have stopped
                    # reading: the rest of an oversized body has nowhere to go.
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
