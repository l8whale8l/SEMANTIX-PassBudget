"""Run comparison read model and human-readable report.

`RunComparison` is derived, never stored. It reads two terminal results and returns a
new document; neither input is mutated. A numeric delta is produced only when the two metric rows
agree on metric code, unit, definition revision, accounting layer and result schema version. When
they do not, both values are still shown and the delta and ratio are `null` with a reason.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from semantix_passbudget.domain.enums import ComparisonReasonCode

COMPARISON_SCHEMA_VERSION = "passbudget-comparison-0.2"

#: Fields that must agree before two metric rows may be subtracted from each other.
COMPATIBILITY_FIELDS = (
    ("unit_code", ComparisonReasonCode.METRIC_UNIT_MISMATCH),
    ("definition_revision", ComparisonReasonCode.METRIC_DEFINITION_MISMATCH),
    ("accounting_layer", ComparisonReasonCode.METRIC_ACCOUNTING_LAYER_MISMATCH),
    ("schema_version", ComparisonReasonCode.METRIC_SCHEMA_REVISION_MISMATCH),
)

SAFETY_TEXT = (
    "이 보고서는 합성·가정 입력에 대한 모델 결과이며 명령 계획, 지상국 예약,\n"
    "실제 지상 수신 또는 운용 승인을 의미하지 않습니다."
)


def _metric_index(result: dict[str, Any]) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in result.get("run_metrics", []):
        key = (
            str(row["metric_code"]),
            str(row["scope_code"]),
            str(row.get("station_key") or ""),
            str(row.get("payload_key") or ""),
        )
        index[key] = row
    return index


def _compare_row(
    key: tuple[str, str, str, str],
    baseline: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
) -> dict[str, Any]:
    metric_code, scope_code, station_key, payload_key = key
    reasons: list[dict[str, str]] = []
    baseline_value = baseline["value_integer"] if baseline else None
    candidate_value = candidate["value_integer"] if candidate else None
    comparable = baseline is not None and candidate is not None
    if comparable:
        assert baseline is not None and candidate is not None
        for field, reason in COMPATIBILITY_FIELDS:
            if baseline.get(field) != candidate.get(field):
                reasons.append({"code": reason.value})
                comparable = False
    else:
        reasons.append({"code": ComparisonReasonCode.METRIC_NOT_COMPUTED_IN_BOTH_RUNS.value})
    delta: int | None = None
    ratio: dict[str, str] | None = None
    if comparable and isinstance(baseline_value, int) and isinstance(candidate_value, int):
        delta = candidate_value - baseline_value
        if baseline_value == 0:
            reasons.append({"code": ComparisonReasonCode.BASELINE_ZERO_RATIO_UNDEFINED.value})
        else:
            exact = Fraction(candidate_value, baseline_value)
            ratio = {"numerator": str(exact.numerator), "denominator": str(exact.denominator)}
    elif comparable:
        reasons.append({"code": ComparisonReasonCode.METRIC_NOT_COMPUTED_IN_BOTH_RUNS.value})
    source = baseline or candidate or {}
    return {
        "metric": metric_code,
        "scope_code": scope_code,
        "station_key": station_key or None,
        "payload_key": payload_key or None,
        "unit": source.get("unit_code"),
        "definition_revision": source.get("definition_revision"),
        "accounting_layer": source.get("accounting_layer"),
        "baseline": baseline_value,
        "candidate": candidate_value,
        "absolute_delta": delta,
        "candidate_to_baseline_ratio": ratio,
        "comparable": comparable and delta is not None,
        "reason_codes": reasons,
    }


def compare_results(
    baseline_result: dict[str, Any], candidate_result: dict[str, Any]
) -> dict[str, Any]:
    baseline_metrics = _metric_index(baseline_result)
    candidate_metrics = _metric_index(candidate_result)
    rows = [
        _compare_row(key, baseline_metrics.get(key), candidate_metrics.get(key))
        for key in sorted(set(baseline_metrics) | set(candidate_metrics))
    ]
    warnings: list[dict[str, str]] = []
    baseline_grade = str(baseline_result.get("decision_grade", ""))
    candidate_grade = str(candidate_result.get("decision_grade", ""))
    if baseline_grade != candidate_grade:
        # Both names are emitted: v1.4 of the golden design calls this
        # COMPARABLE_WITH_EVIDENCE_DIFFERENCE, the P0 specification calls it
        # EVIDENCE_GRADE_MISMATCH keeps unlike evidence grades visibly incomparable.
        warnings.extend(
            {
                "code": code.value,
                "baseline_decision_grade": baseline_grade,
                "candidate_decision_grade": candidate_grade,
            }
            for code in (
                ComparisonReasonCode.COMPARABLE_WITH_EVIDENCE_DIFFERENCE,
                ComparisonReasonCode.EVIDENCE_GRADE_MISMATCH,
            )
        )
    baseline_optimization = _optimization(baseline_result)
    candidate_optimization = _optimization(candidate_result)
    if (
        baseline_optimization["optimization_status"]
        != candidate_optimization["optimization_status"]
    ):
        # One side established optimality and the other did not. The metric deltas are still
        # arithmetic, but reading them as "this scenario is better" would compare a proven
        # optimum against a bounded approximation and attribute the difference to the scenario.
        warnings.append(
            {
                "code": ComparisonReasonCode.OPTIMIZATION_GRADE_MISMATCH.value,
                "baseline_optimization_status": str(baseline_optimization["optimization_status"]),
                "candidate_optimization_status": str(candidate_optimization["optimization_status"]),
                "baseline_execution_strategy": str(baseline_optimization["execution_strategy"]),
                "candidate_execution_strategy": str(candidate_optimization["execution_strategy"]),
            }
        )
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "baseline_fixture_id": baseline_result.get("fixture_id"),
        "candidate_fixture_id": candidate_result.get("fixture_id"),
        "baseline_input_summary": _input_summary(baseline_result),
        "candidate_input_summary": _input_summary(candidate_result),
        "baseline_decision_grade": baseline_grade,
        "candidate_decision_grade": candidate_grade,
        "baseline_optimization": baseline_optimization,
        "candidate_optimization": candidate_optimization,
        "metrics": rows,
        "warnings": warnings,
        "safety_notice": baseline_result.get("safety_notice"),
    }


def _optimization(result: dict[str, Any]) -> dict[str, Any]:
    """One side's optimization grade, defaulted for a result written before the field."""
    block = result.get("optimization") or {}
    return {
        "execution_strategy": block.get("execution_strategy", "UNKNOWN"),
        "optimization_status": block.get("optimization_status", "UNKNOWN"),
        "globally_optimal": block.get("globally_optimal"),
        "algorithm_revision": block.get("algorithm_revision", "UNKNOWN"),
    }


def _input_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "fixture_id": result.get("fixture_id"),
        "analysis_mode": result.get("analysis_mode"),
        "contact_source": result.get("contact_source"),
        "storage_mode": (
            "ENABLED"
            if result.get("storage", {}).get("calculation_status") == "COMPUTED"
            else "NOT_APPLICABLE"
        ),
        "stations": sorted(
            item["station_key"] for item in result.get("metrics", {}).get("stations", [])
        ),
    }


def _mb(value: object) -> str:
    if not isinstance(value, int):
        return "—"
    return f"{value / 1_000_000:.2f} MB"


def render_report(result: dict[str, Any]) -> str:
    metrics = result["metrics"]
    storage = result.get("storage", {})
    # The orbit-dependency line reflects the actual computed status, not a fixed NOT_APPLICABLE:
    # an ORBIT_DERIVED run computes contact windows from the orbit, and reporting that as
    # "NOT_APPLICABLE" misrepresents the result (FE-GAP-05).
    orbit_dependency = result.get("orbit_dependency") or {}
    orbit_status = orbit_dependency.get("calculation_status", "NOT_APPLICABLE")
    orbit_value = orbit_dependency.get("value") or {}
    orbit_kind = orbit_value.get("orbit_kind")
    orbit_line = f"궤도 의존성: {orbit_status}"
    if orbit_status == "COMPUTED" and orbit_kind:
        orbit_line += f" ({orbit_kind}, 가정 기반)"
    lines = [
        f"SEMANTIX PassBudget — {result['fixture_id']}",
        f"상태: {result['calculation_status']} / 근거 등급: {result['decision_grade']}",
        f"접촉 출처: {result.get('contact_source')} / {orbit_line}",
        str(result["safety_notice"]),
        "",
        f"기하학적 접촉 기회: {metrics['geometric_contact_count']}",
        f"충돌 전 후보 용량: {_mb(metrics['candidate_capacity_sum_bytes'])}",
        f"충돌 해결 후 스케줄 용량: {_mb(metrics['scheduled_unique_capacity_bytes'])}",
        f"억제된 후보 용량: {_mb(metrics['suppressed_capacity_bytes'])}",
    ]
    if metrics["payload_allocated_bytes"] is not None:
        lines.extend(
            [
                f"계획상 배치 데이터: {_mb(metrics['payload_allocated_bytes'])}",
                f"분석 종료 시 남은 대기 데이터: {_mb(metrics['payload_remaining_bytes'])}",
                f"할당하지 못한 선택 세션 용량: {_mb(metrics['stranded_capacity_bytes'])}",
            ]
        )
    if storage.get("calculation_status") == "COMPUTED":
        lines.extend(
            [
                "",
                f"저장 점유(최종): {_mb(storage['final_occupancy_bytes'])}",
                f"저장 점유(최대): {_mb(storage['peak_occupancy_bytes'])}",
                f"보호 여유 침범: {_mb(storage['reserve_breach_bytes'])}",
                f"물리 용량 초과: {_mb(storage['hard_overflow_bytes'])}",
                f"거부된 객체: {storage['rejected_object_count']}개 "
                f"({_mb(storage['rejected_bytes'])})",
            ]
        )
    else:
        lines.extend(["", "저장공간 분석: 분석 대상 아님 (0B나 무한 저장을 뜻하지 않습니다)"])
    lines.extend(["", SAFETY_TEXT])
    return "\n".join(lines) + "\n"
