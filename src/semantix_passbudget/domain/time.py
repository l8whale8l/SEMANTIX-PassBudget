from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .errors import DomainValidationError, ErrorDetail

UTC_Z_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<hour>\d{2}):(?P<minute>\d{2}):"
    r"(?P<second>\d{2})(?P<fraction>\.\d{1,6})?Z$"
)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, order=True, slots=True)
class UtcInstant:
    microseconds: int

    @classmethod
    def parse(cls, value: str, field_path: str = "timestamp") -> UtcInstant:
        match = UTC_Z_PATTERN.fullmatch(value)
        if match is None:
            code = "UNSUPPORTED_LEAP_SECOND_WINDOW" if ":60" in value else "INVALID_UTC_TIMESTAMP"
            raise DomainValidationError(
                ErrorDetail(
                    code=code,
                    message="Timestamp must be UTC Z with zero to six fractional digits.",
                    scope="time",
                    field_paths=(field_path,),
                    affected_branches=("contact", "capacity", "schedule"),
                )
            )
        if match.group("second") == "60":
            raise DomainValidationError(
                ErrorDetail(
                    code="UNSUPPORTED_LEAP_SECOND_WINDOW",
                    message="Leap-second windows are not supported and are never shifted silently.",
                    scope="time",
                    field_paths=(field_path,),
                    affected_branches=("contact", "capacity", "schedule"),
                )
            )
        try:
            parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
        except ValueError as exc:
            raise DomainValidationError(
                ErrorDetail(
                    code="INVALID_UTC_TIMESTAMP",
                    message="Timestamp is not a valid calendar instant.",
                    scope="time",
                    field_paths=(field_path,),
                    affected_branches=("contact", "capacity", "schedule"),
                )
            ) from exc
        delta = parsed - EPOCH
        return cls((delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds)

    def isoformat(self) -> str:
        value = EPOCH + timedelta(microseconds=self.microseconds)
        return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True, slots=True)
class TimeInterval:
    start: UtcInstant
    end: UtcInstant

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise DomainValidationError(
                ErrorDetail(
                    code="INVALID_INTERVAL",
                    message="Intervals use [start,end) and require start < end.",
                    scope="time",
                    field_paths=("start", "end"),
                    affected_branches=("contact",),
                )
            )

    @property
    def duration_us(self) -> int:
        return self.end.microseconds - self.start.microseconds

    def intersect(self, other: TimeInterval) -> TimeInterval | None:
        start = max(self.start, other.start)
        end = min(self.end, other.end)
        return TimeInterval(start, end) if start < end else None

    def overlaps(self, other: TimeInterval) -> bool:
        return max(self.start, other.start) < min(self.end, other.end)
