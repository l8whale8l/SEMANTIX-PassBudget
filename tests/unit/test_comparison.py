"""Comparison compatibility rules.

A delta is produced only when the two metric rows agree on unit, definition revision, accounting
layer and result schema version. Otherwise both values are still shown and the delta and ratio are
`null` with a reason, because a wrong number is worse than a missing one.
"""

from __future__ import annotations

from typing import Any

from semantix_passbudget.application.comparison import compare_results, render_report


def _metric(code: str, value: int | None, **overrides: Any) -> dict[str, Any]:
    row = {
        "metric_code": code,
        "scope_code": "RUN",
        "station_key": None,
        "payload_key": None,
        "unit_code": "BYTE",
        "definition_revision": "P0_METRICS_V1",
        "accounting_layer": "LOGICAL_PAYLOAD",
        "schema_version": "passbudget-result-0.2",
        "value_integer": value,
        "calculation_status": "COMPUTED",
    }
    row.update(overrides)
    return row


def _result(
    metrics: list[dict[str, Any]],
    *,
    grade: str = "CONCEPT_ONLY",
    fixture_id: str = "F",
) -> dict[str, Any]:
    return {
        "fixture_id": fixture_id,
        "analysis_mode": "NETWORK_ONLY",
        "contact_source": "SYNTHETIC_INJECTED",
        "decision_grade": grade,
        "safety_notice": "Synthetic model result.",
        "run_metrics": metrics,
        "metrics": {"stations": []},
        "storage": {"calculation_status": "NOT_APPLICABLE"},
    }


def _row(comparison: dict[str, Any], code: str) -> dict[str, Any]:
    return next(row for row in comparison["metrics"] if row["metric"] == code)


def test_compatible_metrics_produce_an_exact_delta_and_ratio() -> None:
    comparison = compare_results(
        _result([_metric("SCHEDULED_UNIQUE_CAPACITY_BYTES", 400_000_000)]),
        _result([_metric("SCHEDULED_UNIQUE_CAPACITY_BYTES", 560_000_000)]),
    )
    row = _row(comparison, "SCHEDULED_UNIQUE_CAPACITY_BYTES")
    assert row["absolute_delta"] == 160_000_000
    assert row["candidate_to_baseline_ratio"] == {"numerator": "7", "denominator": "5"}
    assert row["comparable"] is True
    assert row["reason_codes"] == []


def test_unit_mismatch_shows_both_values_without_a_delta() -> None:
    comparison = compare_results(
        _result([_metric("SCHEDULED_UNIQUE_CAPACITY_BYTES", 400)]),
        _result([_metric("SCHEDULED_UNIQUE_CAPACITY_BYTES", 400, unit_code="MB")]),
    )
    row = _row(comparison, "SCHEDULED_UNIQUE_CAPACITY_BYTES")
    assert (row["baseline"], row["candidate"]) == (400, 400)
    assert row["absolute_delta"] is None
    assert row["candidate_to_baseline_ratio"] is None
    assert {code["code"] for code in row["reason_codes"]} == {"METRIC_UNIT_MISMATCH"}


def test_definition_and_accounting_layer_mismatches_are_named_separately() -> None:
    comparison = compare_results(
        _result(
            [
                _metric("A", 1),
                _metric("B", 1),
                _metric("C", 1),
            ]
        ),
        _result(
            [
                _metric("A", 2, definition_revision="P0_METRICS_V2"),
                _metric("B", 2, accounting_layer="STORAGE_FOOTPRINT"),
                _metric("C", 2, schema_version="passbudget-result-0.3"),
            ]
        ),
    )
    assert {code["code"] for code in _row(comparison, "A")["reason_codes"]} == {
        "METRIC_DEFINITION_MISMATCH"
    }
    assert {code["code"] for code in _row(comparison, "B")["reason_codes"]} == {
        "METRIC_ACCOUNTING_LAYER_MISMATCH"
    }
    assert {code["code"] for code in _row(comparison, "C")["reason_codes"]} == {
        "METRIC_SCHEMA_REVISION_MISMATCH"
    }
    assert all(_row(comparison, code)["absolute_delta"] is None for code in "ABC")


def test_zero_baseline_keeps_the_absolute_delta_and_nulls_the_ratio() -> None:
    comparison = compare_results(
        _result([_metric("PAYLOAD_ALLOCATED_BYTES", 0)]),
        _result([_metric("PAYLOAD_ALLOCATED_BYTES", 145_000_000)]),
    )
    row = _row(comparison, "PAYLOAD_ALLOCATED_BYTES")
    assert row["absolute_delta"] == 145_000_000
    assert row["candidate_to_baseline_ratio"] is None
    assert {code["code"] for code in row["reason_codes"]} == {"BASELINE_ZERO_RATIO_UNDEFINED"}


def test_metric_present_in_only_one_run_is_reported_not_assumed_zero() -> None:
    comparison = compare_results(
        _result([_metric("SCHEDULED_UNIQUE_CAPACITY_BYTES", 1)]),
        _result(
            [
                _metric("SCHEDULED_UNIQUE_CAPACITY_BYTES", 1),
                _metric("PAYLOAD_ALLOCATED_BYTES", 5),
            ]
        ),
    )
    row = _row(comparison, "PAYLOAD_ALLOCATED_BYTES")
    assert row["baseline"] is None
    assert row["candidate"] == 5
    assert row["absolute_delta"] is None
    assert {code["code"] for code in row["reason_codes"]} == {"METRIC_NOT_COMPUTED_IN_BOTH_RUNS"}


def test_evidence_grade_difference_raises_a_warning_under_both_document_names() -> None:
    comparison = compare_results(
        _result([_metric("A", 1)], grade="CONCEPT_ONLY"),
        _result([_metric("A", 2)], grade="ENGINEERING_ESTIMATE"),
    )
    codes = {warning["code"] for warning in comparison["warnings"]}
    assert codes == {"COMPARABLE_WITH_EVIDENCE_DIFFERENCE", "EVIDENCE_GRADE_MISMATCH"}
    # The values are still comparable; only the evidence differs.
    assert _row(comparison, "A")["absolute_delta"] == 1


def test_comparison_does_not_mutate_either_input() -> None:
    baseline = _result([_metric("A", 1)])
    candidate = _result([_metric("A", 2)])
    import copy

    baseline_copy = copy.deepcopy(baseline)
    candidate_copy = copy.deepcopy(candidate)
    compare_results(baseline, candidate)
    assert baseline == baseline_copy
    assert candidate == candidate_copy


def test_report_never_claims_delivery_and_marks_storage_not_applicable() -> None:
    text = render_report(
        {
            "fixture_id": "F",
            "calculation_status": "COMPUTED",
            "decision_grade": "CONCEPT_ONLY",
            "contact_source": "SYNTHETIC_INJECTED",
            "safety_notice": "Synthetic model result.",
            "metrics": {
                "geometric_contact_count": 16,
                "candidate_capacity_sum_bytes": 560_000_000,
                "scheduled_unique_capacity_bytes": 560_000_000,
                "suppressed_capacity_bytes": 0,
                "payload_allocated_bytes": None,
                "payload_remaining_bytes": None,
                "stranded_capacity_bytes": None,
            },
            "storage": {"calculation_status": "NOT_APPLICABLE"},
        }
    )
    assert "560.00 MB" in text
    assert "분석 대상 아님" in text
    for forbidden in ("수신 완료", "전송 성공", "지상 도착", "ACK 확인", "다운로드 완료"):
        assert forbidden not in text
