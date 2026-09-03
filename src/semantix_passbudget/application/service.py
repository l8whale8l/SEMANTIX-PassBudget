from __future__ import annotations

from typing import Any
from uuid import uuid4

from semantix_passbudget.domain.canonical import CANONICALIZATION_REVISION, semantic_hash
from semantix_passbudget.domain.capacity import calculate_contact_capacity
from semantix_passbudget.domain.enums import (
    SAFETY_WARNING_CODES,
    AnalysisMode,
    CalculationStatus,
    ContactSource,
    DecisionGrade,
    DeliveryAssumption,
    ReasonCode,
    ReleaseTrigger,
    RunStatus,
    StorageMode,
    WarningCode,
)
from semantix_passbudget.domain.horizon import (
    MANDATORY_TARDINESS_REVISION,
    OVERLAP_OBJECTIVE_REVISION,
    select_queue_aware_nonoverlap,
)
from semantix_passbudget.domain.ledger import (
    EVENT_ORDER_REVISION,
    LedgerResult,
    PayloadProgress,
    run_ledger,
)
from semantix_passbudget.domain.models import Payload, ScenarioSnapshot
from semantix_passbudget.domain.queue import (
    QUEUE_POLICY_REVISION,
    SERVICE_CLASS_RANK_REVISION,
)
from semantix_passbudget.domain.results import ContactResult
from semantix_passbudget.domain.scheduler import (
    TIE_BREAK_PROFILE_REVISION,
    Candidate,
    select_maximum_nonoverlap,
)
from semantix_passbudget.domain.time import TimeInterval
from semantix_passbudget.ports.contact_provider import ContactProvider
from semantix_passbudget.ports.run_repository import RunRepository, StoredRun

RESULT_SCHEMA_VERSION = "passbudget-result-0.2"
METRIC_DEFINITION_REVISION = "P0_METRICS_V1"
CAPACITY_ACCOUNTING_LAYER = "LOGICAL_PAYLOAD"
DISPLAY_FORMAT_REVISION = "MB_2DP_MIB_4DP_V1"

ENGINE_MANIFEST = {
    "engine_version": "0.2.0",
    "code_revision": "P0_BACKEND_SLICE_2",
    "orbit_provider_revision": "NOT_APPLICABLE",
    "capacity_engine_revision": "EXACT_RATE_SINGLE_FLOOR_V1",
    "scheduler_revision": OVERLAP_OBJECTIVE_REVISION,
    "storage_reducer_revision": EVENT_ORDER_REVISION,
    "constants_revision": "NOT_APPLICABLE",
    "time_reference_revision": "UTC_US_NO_LEAP_SECOND_V1",
    "frame_transform_revision": "NOT_APPLICABLE",
    "event_solver_revision": "NOT_APPLICABLE",
    "time_quantization_revision": "UTC_US_HALF_EVEN_V1",
    "canonicalization_revision": CANONICALIZATION_REVISION,
    "overlap_objective_revision": OVERLAP_OBJECTIVE_REVISION,
    "tie_break_profile_revision": TIE_BREAK_PROFILE_REVISION,
    "mandatory_tardiness_revision": MANDATORY_TARDINESS_REVISION,
    "service_class_rank_revision": SERVICE_CLASS_RANK_REVISION,
    "event_order_revision": EVENT_ORDER_REVISION,
    "display_format_revision": DISPLAY_FORMAT_REVISION,
    "rate_arithmetic_revision": "EXACT_RATIONAL_SUM_FLOOR_ONCE_V1",
}

STAGE_ORDER = (
    "GEOMETRIC_ACCESS",
    "MODELED_CONTACT",
    "CANDIDATE_CAPACITY",
    "NETWORK_SCHEDULE",
    "QUEUE",
    "STORAGE",
)


def _maximum_internal_gap_us(intervals: list[TimeInterval]) -> int | None:
    if len(intervals) < 2:
        return None
    ordered = sorted(intervals, key=lambda item: (item.start, item.end))
    maximum = 0
    current_end = ordered[0].end
    for interval in ordered[1:]:
        if interval.start > current_end:
            maximum = max(maximum, interval.start.microseconds - current_end.microseconds)
        current_end = max(current_end, interval.end)
    return maximum


def _deadline_status(payload: Payload, item: PayloadProgress) -> tuple[str | None, int | None]:
    deadline = payload.deadline_at
    complete_at = item.modeled_tx_complete_at
    if deadline is None:
        return None, None
    if complete_at is None:
        return "INCOMPLETE", None
    if complete_at <= deadline:
        return "ON_TIME", 0
    return "LATE", complete_at.microseconds - deadline.microseconds


def _payload_progress_dict(item: PayloadProgress, payload: Payload) -> dict[str, Any]:
    status, late_by_us = _deadline_status(payload, item)
    return {
        "payload_key": item.payload_key,
        "logical_size_bytes": item.logical_size_bytes,
        "allocated_bytes": item.allocated_bytes,
        "remaining_bytes": item.remaining_bytes,
        "state": (
            "COMPLETED"
            if item.remaining_bytes == 0
            else ("PARTIAL" if item.allocated_bytes > 0 else "NOT_STARTED")
        ),
        "modeled_tx_progress_bytes": item.allocated_bytes,
        "modeled_tx_complete_at": (
            item.modeled_tx_complete_at.isoformat() if item.modeled_tx_complete_at else None
        ),
        "partial_transfer_end_at": (
            item.partial_transfer_end_at.isoformat() if item.partial_transfer_end_at else None
        ),
        "deadline_status": status,
        "deadline_feasible": None if status is None else status != "LATE",
        "late_by_us": late_by_us,
        "delivery_confirmation_state": "NOT_OBSERVED",
        "reason_codes": [{"code": code.value} for code in item.reason_codes],
    }


def snapshot_semantics(snapshot: ScenarioSnapshot, provider_revision: str) -> dict[str, Any]:
    return {
        "schema_version": snapshot.schema_version,
        "canonicalization_revision": CANONICALIZATION_REVISION,
        "fixture_id": snapshot.fixture_id,
        "analysis_mode": snapshot.analysis_mode.value,
        "analysis_window": {
            "start": snapshot.analysis_window.start.isoformat(),
            "end": snapshot.analysis_window.end.isoformat(),
        },
        "contact_source": snapshot.contact_source.value,
        "decision_question": snapshot.decision_question,
        "orbit_dependency": {
            "presence": "PROVIDED",
            "value_state": "NOT_APPLICABLE",
            "value": None,
        },
        "contact_provider_revision": provider_revision,
        "source_revision_id": snapshot.source_revision_id,
        "policy_revision_id": snapshot.policy_revision_id,
        "engine_policy_revisions": {
            "overlap_objective_revision": OVERLAP_OBJECTIVE_REVISION,
            "tie_break_profile_revision": TIE_BREAK_PROFILE_REVISION,
            "event_order_revision": EVENT_ORDER_REVISION,
            "queue_policy_revision": QUEUE_POLICY_REVISION,
            "service_class_rank_revision": SERVICE_CLASS_RANK_REVISION,
            "time_quantization_revision": "UTC_US_HALF_EVEN_V1",
            "display_format_revision": DISPLAY_FORMAT_REVISION,
        },
        "stations": [
            {
                "stable_key": station.stable_key,
                "preference_rank": station.preference_rank,
                "capacity": {
                    "provider": station.capacity.provider.value,
                    "rate_semantics": (
                        station.capacity.rate_semantics.value
                        if station.capacity.rate_semantics
                        else None
                    ),
                    "capacity_accounting_layer": CAPACITY_ACCOUNTING_LAYER,
                    "measurement_point": station.capacity.measurement_point,
                    "rate_scope": (
                        station.capacity.rate_scope.value if station.capacity.rate_scope else None
                    ),
                    "accounted_effects": [
                        effect.value for effect in station.capacity.accounted_effects
                    ],
                    "acquisition_guard_us": station.capacity.acquisition_guard_us,
                    "release_guard_us": station.capacity.release_guard_us,
                    "fixed_capacity_bytes": station.capacity.fixed_capacity_bytes,
                    "byte_reserve": station.capacity.byte_reserve,
                    "time_reserves": [
                        {
                            "start_offset_us": item.start_offset_us,
                            "end_offset_us": item.end_offset_us,
                        }
                        for item in station.capacity.time_reserves
                    ],
                    "rate_unknown": station.capacity.rate_unknown,
                    "evidence_state": station.capacity.evidence_state.value,
                    "source_revision_id": station.capacity.source_revision_id,
                    "rationale": station.capacity.rationale,
                    "active_efficiency": station.capacity.active_efficiency,
                    "rate_segments": [
                        {
                            "ordinal": segment.ordinal,
                            "start_offset_us": segment.start_offset_us,
                            "end_offset_us": segment.end_offset_us,
                            "rate": segment.rate.fraction,
                        }
                        for segment in station.capacity.rate_segments
                    ],
                },
            }
            for station in snapshot.stations
        ],
        "contacts": [
            {
                "stable_key": contact.stable_key,
                "station_key": contact.station_key,
                "true_aos": contact.true_interval.start.isoformat(),
                "true_los": contact.true_interval.end.isoformat(),
            }
            for contact in snapshot.contacts
        ],
        "payloads": [
            {
                "stable_key": payload.stable_key,
                "display_name": payload.display_name,
                "media_type": payload.media_type,
                "producer_kind": payload.producer_kind.value,
                "logical_size_bytes": payload.logical_size_bytes,
                "storage_size_bytes": payload.storage_size_bytes,
                "ready_at": payload.ready_at,
                "service_class": payload.service_class.value,
                "deadline_at": payload.deadline_at,
                "deadline_target": (
                    payload.deadline_target.value if payload.deadline_target else None
                ),
                "post_deadline_action": (
                    payload.post_deadline_action.value if payload.post_deadline_action else None
                ),
                "expiry_at": payload.expiry_at,
                "delete_on_expiry": payload.delete_on_expiry,
                "deadline_severity": payload.deadline_severity,
                "mission_priority": payload.mission_priority,
                "queue_sequence": payload.queue_sequence,
                "segmentation": payload.segmentation.value,
                "chunk_size_bytes": payload.chunk_size_bytes,
                "resume_supported": payload.resume_supported,
                "transfer_start_policy": payload.transfer_start_policy.value,
                "bundle_key": payload.bundle_key,
                "bundle_member_role": (
                    payload.bundle_member_role.value if payload.bundle_member_role else None
                ),
            }
            for payload in snapshot.payloads
        ],
        "dependencies": [
            {
                "predecessor_key": item.predecessor_key,
                "successor_key": item.successor_key,
                "kind": item.kind.value,
            }
            for item in snapshot.dependencies
        ],
        "synthetic_delivery_events": [
            {
                "payload_key": item.payload_key,
                "acknowledged_at": item.acknowledged_at,
                "event_origin": item.event_origin.value,
            }
            for item in snapshot.synthetic_delivery_events
        ],
        "storage": {
            "mode": snapshot.storage.mode.value,
            "physical_capacity_bytes": snapshot.storage.physical_capacity_bytes,
            "reserve_bytes": snapshot.storage.reserve_bytes,
            "initial_occupancy_bytes": snapshot.storage.initial_occupancy_bytes,
            "reserve_enforcement": (
                snapshot.storage.reserve_enforcement.value
                if snapshot.storage.reserve_enforcement
                else None
            ),
            "admission_policy": (
                snapshot.storage.admission_policy.value
                if snapshot.storage.admission_policy
                else None
            ),
            "release_trigger": (
                snapshot.storage.release_trigger.value if snapshot.storage.release_trigger else None
            ),
            "delivery_assumption": (
                snapshot.storage.delivery_assumption.value
                if snapshot.storage.delivery_assumption
                else None
            ),
            "reclaim_granularity": (
                snapshot.storage.reclaim_granularity.value
                if snapshot.storage.reclaim_granularity
                else None
            ),
        },
    }


def _metric_row(
    metric_code: str,
    scope_code: str,
    unit_code: str,
    value: int | None,
    *,
    station_key: str | None = None,
    payload_key: str | None = None,
    accounting_layer: str | None = None,
    status: CalculationStatus = CalculationStatus.COMPUTED,
) -> dict[str, Any]:
    return {
        "metric_code": metric_code,
        "scope_code": scope_code,
        "station_key": station_key,
        "payload_key": payload_key,
        "unit_code": unit_code,
        "definition_revision": METRIC_DEFINITION_REVISION,
        "accounting_layer": accounting_layer,
        "schema_version": RESULT_SCHEMA_VERSION,
        "value_integer": value,
        "calculation_status": (
            CalculationStatus.BLOCKED.value
            if value is None and status is CalculationStatus.COMPUTED
            else status.value
        ),
    }


class RunScenarioService:
    def __init__(self, contact_provider: ContactProvider, repository: RunRepository) -> None:
        self._contact_provider = contact_provider
        self._repository = repository

    @property
    def repository(self) -> RunRepository:
        """The injected persistence adapter. Exposed so the composition root is inspectable."""
        return self._repository

    def validate(self, snapshot: ScenarioSnapshot) -> str:
        snapshot.validate()
        return semantic_hash(
            "INPUT", snapshot_semantics(snapshot, self._contact_provider.provider_revision)
        )

    def _contacts_and_candidates(
        self, snapshot: ScenarioSnapshot
    ) -> tuple[list[ContactResult], list[Candidate]]:
        stations = {station.stable_key: station for station in snapshot.stations}
        contact_results: list[ContactResult] = []
        candidates: list[Candidate] = []
        for contact in self._contact_provider.contacts_for(snapshot):
            station = stations[contact.station_key]
            calculated = calculate_contact_capacity(
                contact, station.capacity, snapshot.analysis_window
            )
            result = ContactResult(
                stable_key=contact.stable_key,
                station_key=contact.station_key,
                true_interval=contact.true_interval,
                modeled_interval=calculated.modeled_interval,
                capacity_bytes=calculated.capacity_bytes,
                calculation_status=calculated.status,
                decision_grade=calculated.grade,
                reason_codes=calculated.reason_codes,
            )
            contact_results.append(result)
            if (
                result.modeled_interval is not None
                and result.capacity_bytes is not None
                and result.capacity_bytes > 0
            ):
                candidates.append(
                    Candidate(
                        stable_key=f"candidate/{contact.stable_key}",
                        station_key=contact.station_key,
                        interval=result.modeled_interval,
                        capacity_bytes=result.capacity_bytes,
                        station_preference_rank=station.preference_rank,
                    )
                )
        return contact_results, candidates

    def run(self, snapshot: ScenarioSnapshot) -> StoredRun:
        snapshot.validate()
        input_payload = snapshot_semantics(snapshot, self._contact_provider.provider_revision)
        input_hash = semantic_hash("INPUT", input_payload)
        stations = {station.stable_key: station for station in snapshot.stations}
        profiles = {key: station.capacity for key, station in stations.items()}
        payloads_by_key = {payload.stable_key: payload for payload in snapshot.payloads}
        contact_results, candidates = self._contacts_and_candidates(snapshot)

        blocked = any(
            item.calculation_status is CalculationStatus.BLOCKED for item in contact_results
        )
        queue_mode = snapshot.analysis_mode is AnalysisMode.QUEUE_AWARE
        selection_reasons: dict[str, ReasonCode] = {}
        if queue_mode and not blocked:
            selected, selection_reasons = select_queue_aware_nonoverlap(
                tuple(candidates),
                profiles,
                snapshot.payloads,
                snapshot.dependencies,
                snapshot.storage,
                snapshot.analysis_window,
                snapshot.synthetic_delivery_events,
            )
        else:
            selected = select_maximum_nonoverlap(tuple(candidates))
            selection_reasons = {
                item.stable_key: ReasonCode.SESSION_SELECTED_MAX_LOGICAL_BYTES for item in selected
            }
        selected_keys = {item.stable_key for item in selected}

        ledger: LedgerResult | None = None
        if not blocked and (queue_mode or snapshot.storage.mode is StorageMode.ENABLED):
            ledger = run_ledger(
                selected,
                profiles,
                snapshot.payloads,
                snapshot.dependencies,
                snapshot.storage,
                snapshot.analysis_window,
                snapshot.synthetic_delivery_events,
            )

        result_content = self._result_content(
            snapshot,
            contact_results,
            candidates,
            selected,
            selected_keys,
            selection_reasons,
            ledger,
            payloads_by_key,
            blocked,
        )
        result_hash = semantic_hash("RESULT", result_content)
        run_id = str(uuid4())
        status = RunStatus.PARTIAL if blocked else RunStatus.SUCCEEDED
        stages = self._stages(snapshot, contact_results, selected, ledger, blocked, len(candidates))
        run_hash = semantic_hash(
            "RUN",
            {
                "run_id": run_id,
                "input_snapshot_hash": input_hash,
                "result_content_hash": result_hash,
                "status": status.value,
                "engine_manifest": ENGINE_MANIFEST,
                "stages": stages,
            },
        )
        stored = StoredRun(
            run_id=run_id,
            status=status.value,
            input_snapshot_hash=input_hash,
            result_content_hash=result_hash,
            run_record_hash=run_hash,
            stages=stages,
            result=result_content,
            snapshot=snapshot,
            input_snapshot_payload=input_payload,
        )
        self._repository.add(stored)
        return stored

    def _stages(
        self,
        snapshot: ScenarioSnapshot,
        contact_results: list[ContactResult],
        selected: tuple[Candidate, ...],
        ledger: LedgerResult | None,
        blocked: bool,
        candidate_count: int,
    ) -> tuple[dict[str, Any], ...]:
        queue_applicable = snapshot.analysis_mode is AnalysisMode.QUEUE_AWARE
        storage_applicable = snapshot.storage.mode is StorageMode.ENABLED
        statuses = {
            "GEOMETRIC_ACCESS": ("SUCCEEDED", len(contact_results)),
            "MODELED_CONTACT": ("SUCCEEDED", len(contact_results)),
            "CANDIDATE_CAPACITY": (
                "BLOCKED" if blocked else "SUCCEEDED",
                candidate_count,
            ),
            "NETWORK_SCHEDULE": ("BLOCKED" if blocked else "SUCCEEDED", len(selected)),
            "QUEUE": (
                "NOT_APPLICABLE"
                if not queue_applicable
                else ("BLOCKED" if ledger is None else "SUCCEEDED"),
                0 if ledger is None else len(ledger.allocations),
            ),
            "STORAGE": (
                "NOT_APPLICABLE"
                if not storage_applicable
                else ("BLOCKED" if ledger is None else "SUCCEEDED"),
                0 if ledger is None else len(ledger.storage.admissions),
            ),
        }
        return tuple(
            {
                "stage_code": code,
                "stage_ordinal": ordinal,
                "status": statuses[code][0],
                "row_count": statuses[code][1],
            }
            for ordinal, code in enumerate(STAGE_ORDER)
        )

    def _result_content(
        self,
        snapshot: ScenarioSnapshot,
        contact_results: list[ContactResult],
        candidates: list[Candidate],
        selected: tuple[Candidate, ...],
        selected_keys: set[str],
        selection_reasons: dict[str, ReasonCode],
        ledger: LedgerResult | None,
        payloads_by_key: dict[str, Payload],
        blocked: bool,
    ) -> dict[str, Any]:
        candidate_sum = None if blocked else sum(item.capacity_bytes for item in candidates)
        scheduled_sum = None if blocked else sum(item.capacity_bytes for item in selected)
        suppressed_sum = (
            None
            if blocked
            else sum(
                item.capacity_bytes for item in candidates if item.stable_key not in selected_keys
            )
        )
        geometric_intervals = [item.true_interval for item in contact_results]
        modeled_intervals = [
            item.modeled_interval for item in contact_results if item.modeled_interval is not None
        ]
        selected_intervals = [item.interval for item in selected]
        modeled_candidate_count = sum(item.modeled_interval is not None for item in contact_results)

        station_metrics: list[dict[str, Any]] = []
        for station_key in sorted({station.stable_key for station in snapshot.stations}):
            station_results = [item for item in contact_results if item.station_key == station_key]
            station_blocked = any(
                item.calculation_status is CalculationStatus.BLOCKED for item in station_results
            )
            station_metrics.append(
                {
                    "station_key": station_key,
                    "geometric_contact_count": len(station_results),
                    "candidate_capacity_sum_bytes": (
                        None
                        if station_blocked
                        else sum(item.capacity_bytes or 0 for item in station_results)
                    ),
                    "calculation_status": (
                        CalculationStatus.BLOCKED.value
                        if station_blocked
                        else CalculationStatus.COMPUTED.value
                    ),
                    "decision_grade": (
                        DecisionGrade.BLOCKED.value
                        if station_blocked
                        else DecisionGrade.CONCEPT_ONLY.value
                    ),
                }
            )

        storage = None if ledger is None else ledger.storage
        storage_applicable = storage is not None and storage.applicable
        allocated_bytes = (
            None if ledger is None else sum(item.allocated_bytes for item in ledger.allocations)
        )
        remaining_bytes = (
            None if ledger is None else sum(item.remaining_bytes for item in ledger.progress)
        )
        proxy_delivery = (
            snapshot.storage.delivery_assumption is DeliveryAssumption.TX_END_EQUALS_DELIVERED
        )
        warnings = [
            {"code": code.value, "scope_stable_key": snapshot.fixture_id}
            for code in SAFETY_WARNING_CODES
        ]
        if snapshot.synthetic_delivery_events:
            warnings.append(
                {
                    "code": WarningCode.SYNTHETIC_TEST_DELIVERY_EVENTS_ONLY.value,
                    "scope_stable_key": snapshot.fixture_id,
                }
            )
        if proxy_delivery:
            warnings.append(
                {
                    "code": WarningCode.ASSUMED_DELIVERY_PROXY_RESULT.value,
                    "scope_stable_key": snapshot.fixture_id,
                }
            )

        metrics = {
            "geometric_contact_count": len(contact_results),
            "modeled_candidate_count": modeled_candidate_count,
            "scheduled_session_count": len(selected),
            "candidate_capacity_sum_bytes": candidate_sum,
            "scheduled_unique_capacity_bytes": scheduled_sum,
            "suppressed_capacity_bytes": suppressed_sum,
            "stranded_capacity_bytes": (None if ledger is None else ledger.stranded_capacity_bytes),
            "geometric_duration_us": sum(item.duration_us for item in geometric_intervals),
            "modeled_candidate_duration_us": sum(item.duration_us for item in modeled_intervals),
            "scheduled_session_duration_us": sum(item.duration_us for item in selected_intervals),
            "geometric_access_gap": {
                "scope": "INTERNAL",
                "max_us": _maximum_internal_gap_us(geometric_intervals),
            },
            "modeled_active_data_gap": {
                "scope": "INTERNAL",
                "max_us": _maximum_internal_gap_us(modeled_intervals),
            },
            "scheduled_session_gap": {
                "scope": "INTERNAL",
                "max_us": _maximum_internal_gap_us(selected_intervals),
            },
            "payload_allocated_bytes": allocated_bytes,
            "payload_remaining_bytes": remaining_bytes,
            "stations": station_metrics,
        }

        byte_layer = CAPACITY_ACCOUNTING_LAYER
        run_metrics: list[dict[str, Any]] = [
            _metric_row("GEOMETRIC_CONTACT_COUNT", "RUN", "COUNT", len(contact_results)),
            _metric_row("MODELED_CANDIDATE_COUNT", "RUN", "COUNT", modeled_candidate_count),
            _metric_row("SCHEDULED_SESSION_COUNT", "RUN", "COUNT", len(selected)),
            _metric_row(
                "CANDIDATE_CAPACITY_SUM_BYTES",
                "RUN",
                "BYTE",
                candidate_sum,
                accounting_layer=byte_layer,
            ),
            _metric_row(
                "SCHEDULED_UNIQUE_CAPACITY_BYTES",
                "RUN",
                "BYTE",
                scheduled_sum,
                accounting_layer=byte_layer,
            ),
            _metric_row(
                "SUPPRESSED_CAPACITY_BYTES",
                "RUN",
                "BYTE",
                suppressed_sum,
                accounting_layer=byte_layer,
            ),
        ]
        for station in station_metrics:
            run_metrics.append(
                _metric_row(
                    "STATION_CANDIDATE_CAPACITY_SUM_BYTES",
                    "STATION",
                    "BYTE",
                    station["candidate_capacity_sum_bytes"],
                    station_key=str(station["station_key"]),
                    accounting_layer=byte_layer,
                )
            )
        for code, value in (
            ("PAYLOAD_ALLOCATED_BYTES", allocated_bytes),
            ("PAYLOAD_REMAINING_BYTES", remaining_bytes),
            ("STRANDED_CAPACITY_BYTES", None if ledger is None else ledger.stranded_capacity_bytes),
        ):
            run_metrics.append(
                _metric_row(
                    code,
                    "RUN",
                    "BYTE",
                    value,
                    accounting_layer=byte_layer,
                    status=(
                        CalculationStatus.COMPUTED
                        if ledger is not None
                        else CalculationStatus.NOT_APPLICABLE
                    ),
                )
            )
        for code, value in (
            (
                "STORAGE_FINAL_OCCUPANCY_BYTES",
                None if storage is None else storage.final_occupancy_bytes,
            ),
            (
                "STORAGE_PEAK_OCCUPANCY_BYTES",
                None if storage is None else storage.peak_occupancy_bytes,
            ),
            (
                "STORAGE_RESERVE_BREACH_BYTES",
                None if storage is None else storage.reserve_breach_bytes,
            ),
            (
                "STORAGE_HARD_OVERFLOW_BYTES",
                None if storage is None else storage.hard_overflow_bytes,
            ),
            ("STORAGE_REJECTED_BYTES", None if storage is None else storage.rejected_bytes),
            ("STORAGE_RELEASED_BYTES", None if storage is None else storage.released_bytes),
        ):
            run_metrics.append(
                _metric_row(
                    code,
                    "RUN",
                    "BYTE",
                    value,
                    accounting_layer="STORAGE_FOOTPRINT",
                    status=(
                        CalculationStatus.COMPUTED
                        if storage_applicable
                        else CalculationStatus.NOT_APPLICABLE
                    ),
                )
            )

        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "fixture_id": snapshot.fixture_id,
            "analysis_mode": snapshot.analysis_mode.value,
            "calculation_status": (
                CalculationStatus.BLOCKED.value if blocked else CalculationStatus.COMPUTED.value
            ),
            "decision_grade": (
                DecisionGrade.BLOCKED.value if blocked else DecisionGrade.CONCEPT_ONLY.value
            ),
            "safety_notice": snapshot.safety_notice,
            "contact_source": snapshot.contact_source.value,
            "orbit_dependency": {
                "calculation_status": CalculationStatus.NOT_APPLICABLE.value,
                "value": None,
            },
            "provenance": {
                "contact_provider": self._contact_provider.provider_revision,
                "source_revision_id": snapshot.source_revision_id,
                "synthetic": snapshot.contact_source is ContactSource.SYNTHETIC_INJECTED,
            },
            "engine_manifest": ENGINE_MANIFEST,
            "geometric_accesses": [item.geometric_dict() for item in contact_results],
            "modeled_contacts": [item.modeled_dict() for item in contact_results],
            "candidate_sessions": [item.candidate_dict() for item in contact_results],
            "scheduled_sessions": [
                {
                    "stable_key": f"scheduled/{item.stable_key.removeprefix('candidate/')}",
                    "candidate_stable_key": item.stable_key,
                    "station_key": item.station_key,
                    "selection_ordinal": ordinal,
                    "usable_start": item.interval.start.isoformat(),
                    "usable_end": item.interval.end.isoformat(),
                    "capacity_bytes": item.capacity_bytes,
                    "calculation_status": CalculationStatus.COMPUTED.value,
                    "decision_grade": DecisionGrade.CONCEPT_ONLY.value,
                    "reason_codes": [
                        {
                            "code": selection_reasons.get(
                                item.stable_key, ReasonCode.SESSION_SELECTED_MAX_LOGICAL_BYTES
                            ).value
                        }
                    ],
                }
                for ordinal, item in enumerate(selected)
            ],
            "suppressed_candidates": [
                {
                    "candidate_stable_key": item.stable_key,
                    "capacity_bytes": item.capacity_bytes,
                    "reason_codes": [
                        {"code": ReasonCode.SESSION_SUPPRESSED_TX_RESOURCE_CONFLICT.value}
                    ],
                }
                for item in candidates
                if item.stable_key not in selected_keys
            ],
            "payload_allocations": (
                []
                if ledger is None
                else [
                    {
                        "stable_key": item.stable_key,
                        "payload_key": item.payload_key,
                        "session_key": item.session_key,
                        "station_key": item.station_key,
                        "allocation_ordinal": item.allocation_ordinal,
                        "logical_offset_start": item.logical_offset_start,
                        "start": item.start.isoformat(),
                        "end": item.end.isoformat(),
                        "allocated_bytes": item.allocated_bytes,
                        "remaining_bytes_after": item.remaining_bytes_after,
                        "modeled_tx_complete_at": (
                            item.modeled_tx_complete_at.isoformat()
                            if item.modeled_tx_complete_at
                            else None
                        ),
                        "deadline_status": _deadline_status(
                            payloads_by_key[item.payload_key],
                            next(
                                progress
                                for progress in ledger.progress
                                if progress.payload_key == item.payload_key
                            ),
                        )[0],
                        "reason_codes": [{"code": item.reason_code.value}],
                    }
                    for item in ledger.allocations
                ]
            ),
            "payload_progress": (
                []
                if ledger is None
                else [
                    _payload_progress_dict(item, payloads_by_key[item.payload_key])
                    for item in ledger.progress
                ]
            ),
            "bundles": (
                []
                if ledger is None
                else [
                    {
                        "bundle_key": item.bundle_key,
                        "modeled_required_members_tx_complete_at": (
                            item.modeled_required_members_tx_complete_at.isoformat()
                            if item.modeled_required_members_tx_complete_at
                            else None
                        ),
                        "assumed_actionable_at": (
                            item.assumed_actionable_at.isoformat()
                            if item.assumed_actionable_at
                            else None
                        ),
                        "delivery_confirmation_state": item.delivery_confirmation_state.value,
                        "actionable_status": item.actionable_status.value,
                        "complete_status": item.complete_status.value,
                        "reason_codes": [{"code": code.value} for code in item.reason_codes],
                    }
                    for item in ledger.bundles
                ]
            ),
            "run_events": (
                []
                if ledger is None
                else [
                    {
                        "event_at": item.event_at.isoformat(),
                        "event_order": item.event_order,
                        "event_domain": item.event_domain.value,
                        "event_kind": item.event_kind.value,
                        "payload_key": item.payload_key,
                        "allocation_key": item.allocation_key,
                        "delta_logical_bytes": item.delta_logical_bytes,
                        "remaining_logical_bytes": item.remaining_logical_bytes,
                        "delta_storage_bytes": item.delta_storage_bytes,
                        "occupancy_bytes": item.occupancy_bytes,
                        "reserve_breach_bytes": item.reserve_breach_bytes,
                        "rejected_bytes": item.rejected_bytes,
                        "reason_code": item.reason_code.value,
                    }
                    for item in ledger.events
                ]
            ),
            "storage": {
                "calculation_status": (
                    CalculationStatus.COMPUTED.value
                    if storage_applicable
                    else CalculationStatus.NOT_APPLICABLE.value
                ),
                "release_trigger": (
                    snapshot.storage.release_trigger.value
                    if snapshot.storage.release_trigger
                    else ReleaseTrigger.NEVER.value
                    if storage_applicable
                    else None
                ),
                "delivery_assumption": (
                    snapshot.storage.delivery_assumption.value
                    if snapshot.storage.delivery_assumption
                    else None
                ),
                "reclaim_granularity": (
                    snapshot.storage.reclaim_granularity.value
                    if snapshot.storage.reclaim_granularity
                    else None
                ),
                "physical_capacity_bytes": None
                if storage is None
                else storage.physical_capacity_bytes,
                "reserve_bytes": None if storage is None else storage.reserve_bytes,
                "usable_limit_bytes": None if storage is None else storage.usable_limit_bytes,
                "final_occupancy_bytes": None if storage is None else storage.final_occupancy_bytes,
                "hard_overflow_bytes": None if storage is None else storage.hard_overflow_bytes,
                "reserve_breach_bytes": None if storage is None else storage.reserve_breach_bytes,
                "peak_occupancy_bytes": None if storage is None else storage.peak_occupancy_bytes,
                "peak_reserve_breach_bytes": None
                if storage is None
                else storage.peak_reserve_breach_bytes,
                "released_bytes": None if storage is None else storage.released_bytes,
                "rejected_object_count": None if storage is None else storage.rejected_object_count,
                "rejected_bytes": None if storage is None else storage.rejected_bytes,
                "admissions": (
                    []
                    if storage is None
                    else [
                        {
                            "payload_key": item.payload_key,
                            "admitted": item.admitted,
                            "occupancy_after_bytes": item.occupancy_after_bytes,
                            "reason_codes": (
                                [{"code": item.reason_code.value}] if item.reason_code else []
                            ),
                        }
                        for item in storage.admissions
                    ]
                ),
                "occupancy_timeline": (
                    []
                    if storage is None
                    else [
                        {"at": item.at.isoformat(), "occupancy_bytes": item.occupancy_bytes}
                        for item in storage.occupancy_timeline
                    ]
                ),
            },
            "metrics": metrics,
            "run_metrics": run_metrics,
            "warnings": warnings,
        }

    def get(self, run_id: str) -> StoredRun | None:
        return self._repository.get(run_id)
