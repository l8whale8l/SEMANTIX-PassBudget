"""The P0 input ceilings, in one place.

`P0_FUNCTIONAL_SPEC.md` §15.4 requires bounds on input size, analysis duration and station and
payload counts so that a public deployment cannot be driven into resource exhaustion. Scattering
those numbers across the DTO layer, the API layer and the domain would give three answers to the
same question, and a caller that reaches the domain directly would pass none of them.

So every ceiling lives here, every ceiling is a plain integer with no environment lookup, and the
only enforcement point that matters -- `ScenarioSnapshot.validate()` -- is the one that every
entry point already goes through. The HTTP layer adds the two ceilings that only exist over HTTP
(request body and free-form revision payload); it does not restate any of the others.

Sizing rule: each ceiling comfortably admits the specification's own reference analysis (one
spacecraft, 20 ground stations, a 7-day window, 10,000 payloads) and refuses well before the
machine does. Where the reference size *is* the ceiling -- payload count -- the reference is
accepted exactly and one more is refused.

Exceeding a ceiling is `INPUT_LIMIT_EXCEEDED`. The error names the limit and the allowed maximum
so a caller can fix the request; it never echoes the input or any value taken from it.
"""

from __future__ import annotations

from .errors import DomainValidationError, ErrorDetail

_MICROSECONDS_PER_DAY = 86_400 * 1_000_000

#: Largest accepted analysis window. The reference scenario is 7 days; a month is the ceiling.
MAX_ANALYSIS_WINDOW_US = 31 * _MICROSECONDS_PER_DAY

#: Reference size is 20.
MAX_STATIONS = 200

#: Reference size is 700 (20 stations x 7 days x 5 passes).
MAX_CONTACTS = 20_000

#: The reference manifest size exactly. 10,000 is accepted; 10,001 is refused.
MAX_PAYLOADS = 10_000

#: A dependency graph denser than two edges per payload is a modelling error, not a scenario.
MAX_DEPENDENCIES = 20_000

#: Per station. A segmented timeline this long already describes every minute of a long pass.
MAX_RATE_SEGMENTS_PER_STATION = 512
MAX_TIME_RESERVES_PER_STATION = 512

#: Synthetic delivery events are a test-only P0 input (`CONFLICT-STORE-01`), never a feed.
MAX_SYNTHETIC_DELIVERY_EVENTS = 10_000

#: HTTP only: the largest request body the API will read. An inline 10,000-payload snapshot is
#: roughly 3 MB of JSON, so this admits the reference scenario sent whole and little more.
MAX_REQUEST_BODY_BYTES = 8 * 1024 * 1024

#: HTTP only: the largest free-form profile revision payload. Profile revisions describe a
#: spacecraft, an orbit or a station; none of them is a megabyte of JSON.
MAX_PROFILE_REVISION_PAYLOAD_BYTES = 256 * 1024


def enforce(
    *,
    limit_name: str,
    actual: int,
    maximum: int,
    unit: str,
    scope: str,
    field_path: str,
    affected_branches: tuple[str, ...] = (),
) -> None:
    """Refuse an input that exceeds a P0 ceiling, before any calculation begins.

    `actual` is a count or a byte length the caller already knows, never a value taken from the
    input, so reporting it leaks nothing while telling the caller how far over they are.
    """
    if actual <= maximum:
        return
    raise DomainValidationError(
        ErrorDetail(
            code="INPUT_LIMIT_EXCEEDED",
            message=(
                f"{limit_name} exceeds the P0 input ceiling: {actual} {unit} against a maximum "
                f"of {maximum}. The request is refused whole; no partial or truncated analysis "
                "is produced."
            ),
            scope=scope,
            field_paths=(field_path,),
            affected_branches=affected_branches,
            details={
                "limit_name": limit_name,
                "limit_maximum": str(maximum),
                "limit_actual": str(actual),
                "limit_unit": unit,
            },
        )
    )
