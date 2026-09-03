from __future__ import annotations

import hashlib
import json
import unicodedata
from enum import Enum
from fractions import Fraction
from typing import Any, Literal

from .time import UtcInstant

CANONICALIZATION_REVISION = "PB-C14N-JSON-V1"
HashKind = Literal["INPUT", "RESULT", "RUN"]

SET_ARRAY_SORT_FIELDS: dict[str, tuple[str, ...]] = {
    "contacts": ("station_key", "true_aos", "true_los", "stable_key"),
    "geometric_accesses": ("station_key", "true_aos", "true_los", "stable_key"),
    "modeled_contacts": ("station_key", "usable_start", "usable_end", "stable_key"),
    "candidate_sessions": ("station_key", "usable_start", "usable_end", "stable_key"),
    "scheduled_sessions": ("station_key", "usable_start", "usable_end", "stable_key"),
    "payloads": ("stable_key",),
    "dependencies": ("predecessor_key", "successor_key", "kind"),
    "payload_allocations": ("session_key", "allocation_ordinal", "stable_key"),
    "payload_progress": ("payload_key",),
    "admissions": ("payload_key",),
    "warnings": ("code", "scope_stable_key"),
    "reason_codes": ("code",),
    "accounted_effects": (),
    "run_events": ("event_at", "event_order"),
    "run_metrics": ("metric_code", "scope_code", "station_key", "payload_key"),
    "bundles": ("bundle_key",),
    "suppressed_candidates": ("candidate_stable_key",),
    "stations": ("station_key", "stable_key"),
}


def _sort_field(value: object) -> str:
    """Sort integers by magnitude, not by their decimal spelling."""
    text = "" if value is None else str(value)
    return text.rjust(24, "0") if text.isdigit() else text


def _sort_key(value: object, fields: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(_sort_field(value.get(field, "")) for field in fields)
    return (_sort_field(value),)


def _normalize(value: Any, path: tuple[str, ...] = ()) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Enum):
        return _normalize(value.value, path)
    if isinstance(value, UtcInstant):
        return value.isoformat()
    if isinstance(value, Fraction):
        return {"d": str(value.denominator), "n": str(value.numerator)}
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        raise TypeError("binary float is not a canonical exact domain value")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        normalized_items = [
            (unicodedata.normalize("NFC", str(key)), _normalize(item, (*path, str(key))))
            for key, item in value.items()
        ]
        normalized_items.sort(key=lambda item: item[0].encode("utf-8"))
        return {key: item for key, item in normalized_items}
    if isinstance(value, (list, tuple)):
        items = [_normalize(item, path) for item in value]
        field = path[-1] if path else ""
        sort_fields = SET_ARRAY_SORT_FIELDS.get(field)
        if sort_fields is not None:
            items.sort(key=lambda item: _sort_key(item, sort_fields))
        return items
    raise TypeError(f"unsupported canonical value type: {type(value).__name__}")


def canonical_bytes(value: object) -> bytes:
    normalized = _normalize(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def semantic_hash(kind: HashKind, value: object) -> str:
    frame = f"SEMANTIX_PASSBUDGET\0{kind}\0{CANONICALIZATION_REVISION}\0".encode()
    return hashlib.sha256(frame + canonical_bytes(value)).hexdigest()
