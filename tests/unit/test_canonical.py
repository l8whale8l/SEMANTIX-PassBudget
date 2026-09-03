from __future__ import annotations

import unicodedata
from fractions import Fraction

import pytest

from semantix_passbudget.domain.canonical import canonical_bytes, semantic_hash
from tests.reference_c14n import digest, encode


def _vector(reverse: bool = False, decomposed: bool = False) -> dict[str, object]:
    name = "Café" if not decomposed else unicodedata.normalize("NFD", "Café")
    stations = [
        {"stable_key": "GS-B", "bytes": 9_007_199_254_740_993},
        {"stable_key": "GS-A", "rate": Fraction(6, 8), "name": name},
    ]
    if reverse:
        stations.reverse()
    return {
        "z": {"presence": "OMITTED"},
        "a": {"value_state": "NOT_APPLICABLE", "value": None},
        "stations": stations,
        "sequence": ["first", "second"],
    }


def test_independent_canonical_vectors_and_permutations() -> None:
    variants = (_vector(), _vector(True), _vector(False, True), _vector(True, True))
    expected_bytes = encode(variants[0])
    expected_hash = digest("INPUT", variants[0])
    literal_bytes = (
        b'{"a":{"value":null,"value_state":"NOT_APPLICABLE"},'
        b'"sequence":["first","second"],"stations":['
        b'{"name":"Caf\xc3\xa9","rate":{"d":"4","n":"3"},"stable_key":"GS-A"},'
        b'{"bytes":"9007199254740993","stable_key":"GS-B"}],'
        b'"z":{"presence":"OMITTED"}}'
    )
    literal_hash = "c940b1124f7d85470a4b55ff219722bdb006ee3e1434039423152c4348260c15"
    assert expected_bytes == literal_bytes
    assert expected_hash == literal_hash
    assert all(canonical_bytes(vector) == expected_bytes for vector in variants)
    assert all(semantic_hash("INPUT", vector) == expected_hash for vector in variants)
    assert canonical_bytes(variants[0]) == expected_bytes


def test_ordered_array_is_preserved() -> None:
    forward = _vector()
    reverse = _vector()
    reverse["sequence"] = ["second", "first"]
    assert semantic_hash("INPUT", forward) != semantic_hash("INPUT", reverse)


def test_float_is_rejected() -> None:
    with pytest.raises(TypeError):
        canonical_bytes({"capacity": 1.5})


def test_integers_beyond_double_precision_stay_exact() -> None:
    """AC-19: a byte count above 2^53 must not pass through a binary float anywhere."""
    huge = 2**53 + 1
    encoded = canonical_bytes({"bytes": huge, "product": huge * 3})
    assert b'"bytes":"9007199254740993"' in encoded
    assert b'"product":"27021597764222979"' in encoded
    assert encoded == encode({"bytes": huge, "product": huge * 3})


def test_rational_is_reduced_and_permutation_stable() -> None:
    left = {"rate": Fraction(1_500_000, 2), "unit": "bit/s"}
    right = {"unit": "bit/s", "rate": Fraction(3_000_000, 4)}
    assert canonical_bytes(left) == canonical_bytes(right) == encode(left)
    assert b'{"d":"1","n":"750000"}' in canonical_bytes(left)


def test_set_arrays_sort_numeric_fields_by_magnitude() -> None:
    """Event order 2 must sort before 10, not lexically after it."""
    events = [
        {"event_at": "2027-01-01T00:00:00.000000Z", "event_order": order} for order in (10, 2, 1)
    ]
    encoded = canonical_bytes({"run_events": events})
    assert encoded.index(b'"event_order":"1"') < encoded.index(b'"event_order":"2"')
    assert encoded.index(b'"event_order":"2"') < encoded.index(b'"event_order":"10"')
    assert canonical_bytes({"run_events": list(reversed(events))}) == encoded


def test_unit_normalisation_is_not_silently_applied() -> None:
    """A megabyte and a byte count are different canonical facts, never merged."""
    assert canonical_bytes({"value": 1, "unit": "MB"}) != canonical_bytes(
        {"value": 1_000_000, "unit": "BYTE"}
    )


def test_canonical_object_is_json_safe_and_matches_canonical_bytes() -> None:
    """Adapters store `canonical_object`; it must be exactly what the hash covers."""
    import json

    from semantix_passbudget.domain.canonical import canonical_object

    value = _vector()
    obj = canonical_object(value)
    encoded = json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    assert encoded.encode("utf-8") == canonical_bytes(value)
    # Round-tripping through JSON changes nothing, which is what a jsonb column needs.
    assert json.loads(encoded) == obj
