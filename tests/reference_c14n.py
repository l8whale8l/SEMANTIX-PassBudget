"""Independent test oracle: never import the production canonicalization module."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from fractions import Fraction
from typing import Any

REVISION = "PB-C14N-JSON-V1"
SET_FIELDS = {
    "stations": ("stable_key",),
    "contacts": ("station_key", "true_aos", "true_los", "stable_key"),
    "warnings": ("code", "scope_stable_key"),
}


def _key(item: object, fields: tuple[str, ...]) -> tuple[str, ...]:
    assert isinstance(item, dict)
    return tuple(str(item.get(field, "")) for field in fields)


def normalize(value: Any, field: str = "") -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        raise TypeError("float is forbidden")
    if isinstance(value, Fraction):
        return {"d": str(value.denominator), "n": str(value.numerator)}
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        pairs = [
            (unicodedata.normalize("NFC", str(key)), normalize(item, str(key)))
            for key, item in value.items()
        ]
        pairs.sort(key=lambda pair: pair[0].encode("utf-8"))
        return dict(pairs)
    if isinstance(value, (list, tuple)):
        result = [normalize(item) for item in value]
        if field in SET_FIELDS:
            result.sort(key=lambda item: _key(item, SET_FIELDS[field]))
        return result
    raise TypeError(type(value).__name__)


def encode(value: object) -> bytes:
    return json.dumps(
        normalize(value), ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()


def digest(kind: str, value: object) -> str:
    frame = f"SEMANTIX_PASSBUDGET\0{kind}\0{REVISION}\0".encode()
    return hashlib.sha256(frame + encode(value)).hexdigest()
