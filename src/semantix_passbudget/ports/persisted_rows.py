"""Pure result <-> typed-row mapping.

This module contains no SQL and no database dependency, so the mapping can be tested without a
server: `rows_view(result_rows(result))` is a canonical projection of everything the relational
schema stores. The repository writes exactly these rows and reads exactly these rows back, so a
round-trip that preserves `rows_view` preserves every persisted fact, independently of UUIDs and
of insertion order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from semantix_passbudget.domain.canonical import canonical_bytes, semantic_hash

RESULT_KIND_BY_PREFIX = {
    "geometric/": "GEOMETRIC_ACCESS",
    "modeled/": "MODELED_CONTACT",
    "candidate/": "CANDIDATE_SESSION",
    "scheduled/": "SCHEDULED_SESSION",
    "allocation/": "TRANSFER_ALLOCATION",
    "event/": "RUN_EVENT",
    "metric/": "METRIC",
    "annotation/": "ANNOTATION",
}


@dataclass(frozen=True, slots=True)
class PersistedRows:
    results: tuple[dict[str, Any], ...]
    geometric: tuple[dict[str, Any], ...]
    modeled: tuple[dict[str, Any], ...]
    candidates: tuple[dict[str, Any], ...]
    scheduled: tuple[dict[str, Any], ...]
    allocations: tuple[dict[str, Any], ...]
    events: tuple[dict[str, Any], ...]
    metrics: tuple[dict[str, Any], ...]
    annotations: tuple[dict[str, Any], ...]


def _reason(codes: list[dict[str, str]]) -> str | None:
    return codes[0]["code"] if codes else None


def _event_key(event: dict[str, Any]) -> str:
    stamp = str(event["event_at"]).replace(":", "-").replace(".", "-")
    return f"event/{stamp}/{int(event['event_order']):04d}"


def _metric_key(metric: dict[str, Any]) -> str:
    parts = [str(metric["metric_code"])]
    if metric.get("station_key"):
        parts.append(str(metric["station_key"]))
    if metric.get("payload_key"):
        parts.append(str(metric["payload_key"]))
    return "metric/" + "/".join(parts)


def result_rows(result: dict[str, Any]) -> PersistedRows:
    """Project a computed result onto the typed rows of the accepted schema."""
    results: list[dict[str, Any]] = []
    geometric: list[dict[str, Any]] = []
    modeled: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    scheduled: list[dict[str, Any]] = []
    allocations: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []

    def add_result(stable_key: str, kind: str, status: str, grade: str | None) -> None:
        results.append(
            {
                "stable_key": stable_key,
                "result_kind": kind,
                "calculation_status": status,
                "decision_grade": grade
                if status in {"COMPUTED", "KNOWN_ZERO"}
                else ("BLOCKED" if status == "BLOCKED" else None),
            }
        )

    contact_source = str(result.get("contact_source", "SYNTHETIC_INJECTED"))
    for item in result["geometric_accesses"]:
        add_result(
            item["stable_key"],
            "GEOMETRIC_ACCESS",
            item["calculation_status"],
            item["decision_grade"],
        )
        geometric.append(
            {
                "stable_key": item["stable_key"],
                "station_key": item["station_key"],
                "true_aos": item["true_aos"],
                "true_los": item["true_los"],
                # The reported interval is already clipped to the window, so the in-window interval
                # equals [true_aos, true_los). An ORBIT_DERIVED access also carries a peak elevation
                # and its time; a SYNTHETIC one omits those keys, so the defaults reproduce the
                # original synthetic row byte for byte.
                "clipped_start": item["true_aos"],
                "clipped_end": item["true_los"],
                "maximum_elevation_udeg": item.get("maximum_elevation_udeg"),
                "maximum_elevation_at": item.get("maximum_elevation_at"),
                "contact_source": contact_source,
            }
        )
    for item in result["modeled_contacts"]:
        add_result(
            item["stable_key"],
            "MODELED_CONTACT",
            item["calculation_status"],
            item["decision_grade"],
        )
        modeled.append(
            {
                "stable_key": item["stable_key"],
                "geometric_stable_key": item["geometric_stable_key"],
                "link_compatibility": "ELIGIBLE" if item["usable_start"] is not None else "UNKNOWN",
                "usable_start": item["usable_start"],
                "usable_end": item["usable_end"],
                "primary_reason_code": _reason(item["reason_codes"]),
            }
        )
    for item in result["candidate_sessions"]:
        add_result(
            item["stable_key"],
            "CANDIDATE_SESSION",
            item["calculation_status"],
            item["decision_grade"],
        )
        candidates.append(
            {
                "stable_key": item["stable_key"],
                "modeled_stable_key": item["modeled_stable_key"],
                "capacity_bytes": item["capacity_bytes"],
                "conflict_component_key": None,
            }
        )
    for item in result["scheduled_sessions"]:
        add_result(
            item["stable_key"],
            "SCHEDULED_SESSION",
            item["calculation_status"],
            item["decision_grade"],
        )
        scheduled.append(
            {
                "stable_key": item["stable_key"],
                "candidate_stable_key": item["candidate_stable_key"],
                "selection_ordinal": item["selection_ordinal"],
                "primary_reason_code": (
                    _reason(item["reason_codes"]) or "SESSION_SELECTED_TIE_BREAK"
                ),
            }
        )
    progress_by_key = {item["payload_key"]: item for item in result.get("payload_progress", [])}
    for item in result.get("payload_allocations", []):
        add_result(item["stable_key"], "TRANSFER_ALLOCATION", "COMPUTED", "CONCEPT_ONLY")
        allocations.append(
            {
                "stable_key": item["stable_key"],
                "scheduled_session_stable_key": "scheduled/"
                + str(item["session_key"]).removeprefix("candidate/"),
                "payload_key": item["payload_key"],
                "allocation_ordinal": item["allocation_ordinal"],
                "logical_offset_start": item["logical_offset_start"],
                "logical_bytes": item["allocated_bytes"],
                "started_at": item["start"],
                "ended_at": item["end"],
                "modeled_progress_after_bytes": item["logical_offset_start"]
                + item["allocated_bytes"],
                "modeled_tx_complete_at": item["modeled_tx_complete_at"],
                "deadline_status": item["deadline_status"],
                "remaining_after_bytes": item["remaining_bytes_after"],
                "primary_reason_code": (
                    _reason(item["reason_codes"]) or "PAYLOAD_SELECTED_MANDATORY"
                ),
            }
        )
    for item in result.get("run_events", []):
        key = _event_key(item)
        add_result(key, "RUN_EVENT", "COMPUTED", "CONCEPT_ONLY")
        events.append(
            {
                "stable_key": key,
                "event_at": item["event_at"],
                "event_order": item["event_order"],
                "event_domain": item["event_domain"],
                "event_kind": item["event_kind"],
                "payload_key": item["payload_key"],
                "allocation_stable_key": item["allocation_key"],
                "delta_logical_bytes": item["delta_logical_bytes"],
                "remaining_logical_bytes": item["remaining_logical_bytes"],
                "delta_storage_bytes": item["delta_storage_bytes"],
                "occupancy_bytes": item["occupancy_bytes"],
                "reserve_breach_bytes": item["reserve_breach_bytes"],
                "rejected_bytes": item["rejected_bytes"],
                "reason_code": item["reason_code"],
            }
        )
    for item in result.get("run_metrics", []):
        key = _metric_key(item)
        add_result(key, "METRIC", item["calculation_status"], None)
        metrics.append(
            {
                "stable_key": key,
                "metric_code": item["metric_code"],
                "scope_code": item["scope_code"],
                "station_key": item["station_key"],
                "payload_key": item["payload_key"],
                "unit_code": item["unit_code"],
                "definition_revision": item["definition_revision"],
                "accounting_layer": item["accounting_layer"],
                "value_integer": item["value_integer"],
            }
        )

    ordinal = 0
    for warning in result.get("warnings", []):
        key = f"annotation/warning/{ordinal:04d}"
        add_result(key, "ANNOTATION", "COMPUTED", "CONCEPT_ONLY")
        annotations.append(
            {
                "stable_key": key,
                "subject_stable_key": None,
                "annotation_kind": "WARNING",
                "code": warning["code"],
                "severity": "WARNING",
                "ordinal": ordinal,
                "rule_revision": "P0_SAFETY_WARNINGS_V1",
                "criterion_code": None,
                "criterion_value_text": warning["scope_stable_key"],
            }
        )
        ordinal += 1
    for suppressed in result.get("suppressed_candidates", []):
        key = f"annotation/suppressed/{ordinal:04d}"
        add_result(key, "ANNOTATION", "COMPUTED", "CONCEPT_ONLY")
        annotations.append(
            {
                "stable_key": key,
                "subject_stable_key": suppressed["candidate_stable_key"],
                "annotation_kind": "DECISION_REASON",
                "code": _reason(suppressed["reason_codes"])
                or "SESSION_SUPPRESSED_TX_RESOURCE_CONFLICT",
                "severity": "INFO",
                "ordinal": ordinal,
                "rule_revision": "P0_DECISION_TRACE_V1",
                "criterion_code": "SUPPRESSED_CAPACITY_BYTES",
                "criterion_value_text": None,
            }
        )
        ordinal += 1
    for payload_key in sorted(progress_by_key):
        for code in progress_by_key[payload_key]["reason_codes"]:
            key = f"annotation/payload/{ordinal:04d}"
            add_result(key, "ANNOTATION", "COMPUTED", "CONCEPT_ONLY")
            annotations.append(
                {
                    "stable_key": key,
                    "subject_stable_key": None,
                    "annotation_kind": "DECISION_REASON",
                    "code": code["code"],
                    "severity": "INFO",
                    "ordinal": ordinal,
                    "rule_revision": "P0_DECISION_TRACE_V1",
                    "criterion_code": "PAYLOAD",
                    "criterion_value_text": payload_key,
                }
            )
            ordinal += 1

    return PersistedRows(
        results=tuple(results),
        geometric=tuple(geometric),
        modeled=tuple(modeled),
        candidates=tuple(candidates),
        scheduled=tuple(scheduled),
        allocations=tuple(allocations),
        events=tuple(events),
        metrics=tuple(metrics),
        annotations=tuple(annotations),
    )


def rows_view(rows: PersistedRows) -> dict[str, Any]:
    """Order-independent canonical projection of the persisted rows."""

    def by_key(items: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
        return sorted(items, key=lambda item: str(item["stable_key"]))

    return {
        "results": by_key(rows.results),
        "geometric_accesses": by_key(rows.geometric),
        "modeled_contacts": by_key(rows.modeled),
        "candidate_sessions": by_key(rows.candidates),
        "scheduled_sessions": by_key(rows.scheduled),
        "transfer_allocations": by_key(rows.allocations),
        "run_events": by_key(rows.events),
        "run_metrics": by_key(rows.metrics),
        "run_annotations": by_key(rows.annotations),
    }


def rows_hash(rows: PersistedRows) -> str:
    return semantic_hash("RESULT", rows_view(rows))


def rows_bytes(rows: PersistedRows) -> bytes:
    return canonical_bytes(rows_view(rows))
