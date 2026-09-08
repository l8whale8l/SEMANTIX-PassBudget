"""PostgreSQL persistence adapter.

Implements the same `RunRepository` contract as the in-memory adapter. Everything is written as
typed relational rows: the canonical snapshot bytes are stored *alongside* the typed rows as an
immutable execution artifact, never instead of them.

Safety rules enforced here:

* every statement is a parameterised SQLAlchemy Core construct, never string interpolation;
* no connection string, credential or host path ever reaches a log line, an exception message or
  a returned error; database failures are re-raised as a redacted `PersistenceError`;
* a terminal run is written once and never updated, matching the database triggers;
* insertion order never affects the stored semantics, because every cross-row link is resolved
  through run-local stable keys rather than through UUID ordering.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, delete, insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from semantix_passbudget.adapters.postgres import schema as tables
from semantix_passbudget.application.decompose import decompose_snapshot
from semantix_passbudget.domain.canonical import (
    CANONICALIZATION_REVISION,
    canonical_bytes,
    canonical_object,
)
from semantix_passbudget.domain.enums import (
    AnalysisMode,
    ContactSource,
    ProfileKind,
    StorageMode,
)
from semantix_passbudget.domain.models import ScenarioSnapshot
from semantix_passbudget.ports.persisted_rows import PersistedRows, result_rows
from semantix_passbudget.ports.run_repository import StoredRun

JSON_SCHEMA_ID = "semantix.passbudget.input-snapshot.v0.2"


class PersistenceError(RuntimeError):
    """Redacted persistence failure.

    The originating driver error is deliberately not chained into the message so that a database
    URL, a host name or a credential can never reach an API response or a log line.
    """


@contextmanager
def _redacted(operation: str) -> Iterator[None]:
    try:
        yield
    except SQLAlchemyError:  # pragma: no cover - exercised by the postgres suite
        # Do not instantiate or chain the driver exception. SQLAlchemy DBAPI exceptions require
        # constructor arguments, and their rendered context can contain connection details.
        raise PersistenceError(f"persistence operation failed: {operation}") from None


def _instant(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _digest(value: object) -> bytes:
    return hashlib.sha256(canonical_bytes(value)).digest()


class PostgresRunRepository:
    """Run and result persistence against the accepted PostgreSQL 16 schema."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------ writing

    def add(self, run: StoredRun) -> None:
        if run.snapshot is None:
            raise PersistenceError(
                "a persisted run requires the resolved input snapshot it was computed from"
            )
        if self.get(run.run_id) is not None:
            raise PersistenceError("run identifiers are immutable and may not be overwritten")
        with _redacted("store run"), self._engine.begin() as connection:
            revision_id, station_ids, payload_ids = self._ensure_scenario(connection, run.snapshot)
            snapshot_id = self._ensure_snapshot(connection, run, revision_id)
            manifest_id = self._ensure_manifest(connection, run.result["engine_manifest"])
            self._write_run(connection, run, snapshot_id, manifest_id, station_ids, payload_ids)

    def _ensure_profile(
        self,
        connection: Any,
        stable_key: str,
        kind: ProfileKind,
        name: str,
        payload: Mapping[str, Any],
    ) -> str:
        existing = connection.execute(
            select(tables.profile.c.current_revision_id).where(
                tables.profile.c.stable_key == stable_key
            )
        ).first()
        if existing is not None and existing[0] is not None:
            return str(existing[0])
        profile_id = str(uuid4())
        if existing is None:
            connection.execute(
                insert(tables.profile).values(
                    id=profile_id,
                    stable_key=stable_key,
                    kind=kind.value,
                    name=name[:160],
                    description=None,
                    is_preset=True,
                )
            )
        revision_id = str(uuid4())
        connection.execute(
            insert(tables.profile_revision).values(
                id=revision_id,
                profile_id=profile_id,
                profile_kind=kind.value,
                revision_no=1,
                lifecycle_status="DRAFT",
                schema_version="passbudget-profile-0.2",
                label=f"{stable_key} r1",
                change_note=None,
                based_on_revision_id=None,
            )
        )
        self._write_typed_profile(connection, revision_id, kind, payload)
        connection.execute(
            update(tables.profile_revision)
            .where(tables.profile_revision.c.id == revision_id)
            .values(
                lifecycle_status="PUBLISHED",
                semantic_hash=_digest(dict(payload)),
                published_at=datetime.now(UTC),
            )
        )
        connection.execute(
            update(tables.profile)
            .where(tables.profile.c.id == profile_id)
            .values(current_revision_id=revision_id)
        )
        return revision_id

    def _write_typed_profile(
        self, connection: Any, revision_id: str, kind: ProfileKind, payload: Mapping[str, Any]
    ) -> None:
        if kind is ProfileKind.SPACECRAFT:
            return  # SPACECRAFT is identity-only in P0; the shared revision is the typed identity.
        if kind is ProfileKind.ORBIT:
            tle_digest = payload["tle_content_sha256"]
            connection.execute(
                insert(tables.orbit_revision).values(
                    revision_id=revision_id,
                    profile_kind=kind.value,
                    orbit_kind=payload["orbit_kind"],
                    epoch_at=_instant(payload["epoch_at"]),
                    reference_frame=payload["reference_frame"],
                    time_scale=payload["time_scale"],
                    propagator_revision=payload["propagator_revision"],
                    tle_line1=payload["tle_line1"],
                    tle_line2=payload["tle_line2"],
                    tle_provider=payload["tle_provider"],
                    tle_retrieved_at=_instant(payload["tle_retrieved_at"]),
                    tle_content_sha256=(
                        bytes.fromhex(tle_digest) if tle_digest is not None else None
                    ),
                    earth_radius_m=payload["earth_radius_m"],
                    altitude_m=payload["altitude_m"],
                    inclination_udeg=payload["inclination_udeg"],
                    raan_udeg=payload["raan_udeg"],
                    argument_of_latitude_udeg=payload["argument_of_latitude_udeg"],
                )
            )
            return
        if kind is ProfileKind.GROUND_STATION:
            connection.execute(
                insert(tables.ground_station_revision).values(
                    revision_id=revision_id,
                    profile_kind=kind.value,
                    latitude_udeg=payload["latitude_udeg"],
                    longitude_udeg=payload["longitude_udeg"],
                    ellipsoidal_height_mm=payload["ellipsoidal_height_mm"],
                    rx_resource_key=payload["rx_resource_key"],
                )
            )
            return
        if kind is ProfileKind.COMMUNICATION:
            connection.execute(
                insert(tables.communication_revision).values(
                    revision_id=revision_id,
                    profile_kind=kind.value,
                    provider_kind=payload["provider_kind"],
                    fixed_capacity_bytes=payload["fixed_capacity_bytes"],
                    rate_semantics=payload["rate_semantics"],
                    measurement_point=payload["measurement_point"],
                    rate_scope=payload["rate_scope"],
                    accounted_effects=list(payload["accounted_effects"]),
                    acquisition_guard_us=payload["acquisition_guard_us"],
                    release_guard_us=payload["release_guard_us"],
                    reserve_kind=payload["reserve_kind"],
                    reserve_bytes=payload["reserve_bytes"],
                    capacity_accounting_layer=payload["capacity_accounting_layer"],
                )
            )
            for segment in payload["timeline_segments"]:
                connection.execute(
                    insert(tables.communication_timeline_segment).values(
                        revision_id=revision_id,
                        segment_kind=segment["segment_kind"],
                        ordinal=segment["ordinal"],
                        start_offset_us=segment["start_offset_us"],
                        end_offset_us=segment["end_offset_us"],
                        rate_numerator_bits=segment["rate_numerator_bits"],
                        rate_denominator_seconds=segment["rate_denominator_seconds"],
                    )
                )
            return
        if kind is ProfileKind.PAYLOAD_TYPE:
            connection.execute(
                insert(tables.payload_type_revision).values(
                    revision_id=revision_id,
                    profile_kind=kind.value,
                    media_type=payload["media_type"],
                    serializer_revision=payload["serializer_revision"],
                    segmentation=payload["segmentation"],
                    fixed_chunk_bytes=payload["fixed_chunk_bytes"],
                    resume_allowed=payload["resume_allowed"],
                    partial_product_usable=payload["partial_product_usable"],
                    completion_rule_revision=payload["completion_rule_revision"],
                )
            )
            return
        connection.execute(
            insert(tables.policy_revision).values(
                revision_id=revision_id,
                profile_kind=kind.value,
                policy_kind=payload["policy_kind"],
                comparator_revision=payload["comparator_revision"],
                objective_revision=payload["objective_revision"],
                tie_break_revision=payload["tie_break_revision"],
                starvation_guard=payload["starvation_guard"],
            )
        )

    def _ensure_scenario(
        self, connection: Any, snapshot: ScenarioSnapshot
    ) -> tuple[str, dict[str, str], dict[str, str]]:
        graph = decompose_snapshot(snapshot)
        revisions = {
            spec.stable_key: self._ensure_profile(
                connection, spec.stable_key, spec.kind, spec.name, spec.payload
            )
            for spec in graph.profiles
        }
        scenario_key = snapshot.fixture_id
        row = connection.execute(
            select(tables.scenario.c.id).where(tables.scenario.c.stable_key == scenario_key)
        ).first()
        if row is None:
            scenario_id = str(uuid4())
            connection.execute(
                insert(tables.scenario).values(
                    id=scenario_id,
                    stable_key=scenario_key,
                    name=scenario_key[:160],
                    description=snapshot.decision_question[:1000],
                    is_preset=True,
                )
            )
        else:
            scenario_id = str(row[0])
        revision_hash = _digest(
            {
                "scenario": scenario_key,
                "window": snapshot.analysis_window.start.isoformat()
                + "/"
                + snapshot.analysis_window.end.isoformat(),
                "mode": snapshot.analysis_mode.value,
                "stations": [item.stable_key for item in graph.stations],
                "payloads": [item.stable_key for item in graph.payloads],
                "decision_question": snapshot.decision_question,
            }
        )
        existing = connection.execute(
            select(tables.scenario_revision.c.id).where(
                tables.scenario_revision.c.scenario_id == scenario_id,
                tables.scenario_revision.c.semantic_hash == revision_hash,
            )
        ).first()
        if existing is not None:
            revision_id = str(existing[0])
            return (
                revision_id,
                self._station_ids(connection, revision_id),
                self._payload_ids(connection, revision_id),
            )

        count = connection.execute(
            select(tables.scenario_revision.c.id).where(
                tables.scenario_revision.c.scenario_id == scenario_id
            )
        ).fetchall()
        revision_id = str(uuid4())
        storage = snapshot.storage
        enabled = storage.mode is StorageMode.ENABLED
        orbit_derived = snapshot.contact_source is ContactSource.ORBIT_DERIVED
        connection.execute(
            insert(tables.scenario_revision).values(
                id=revision_id,
                scenario_id=scenario_id,
                revision_no=len(count) + 1,
                lifecycle_status="DRAFT",
                schema_version=snapshot.schema_version[:32],
                based_on_revision_id=None,
                decision_question=snapshot.decision_question[:1000],
                analysis_start=_instant(snapshot.analysis_window.start.isoformat()),
                analysis_end=_instant(snapshot.analysis_window.end.isoformat()),
                analysis_mode=snapshot.analysis_mode.value,
                spacecraft_revision_id=revisions[graph.spacecraft_key],
                spacecraft_profile_kind="SPACECRAFT",
                orbit_revision_id=(revisions[graph.orbit_key] if graph.orbit_key else None),
                policy_revision_id=(
                    revisions[graph.policy_key] if graph.policy_key is not None else None
                ),
                storage_mode=storage.mode.value,
                physical_capacity_bytes=storage.physical_capacity_bytes,
                protected_reserve_bytes=storage.reserve_bytes if enabled else None,
                initial_nonqueue_bytes=storage.initial_occupancy_bytes if enabled else None,
                reserve_enforcement=(
                    storage.reserve_enforcement.value if storage.reserve_enforcement else None
                ),
                storage_admission_policy=(
                    storage.admission_policy.value if storage.admission_policy else None
                ),
                reclaim_granularity=(
                    storage.reclaim_granularity.value if storage.reclaim_granularity else None
                ),
                release_trigger=(
                    storage.release_trigger.value if storage.release_trigger else None
                ),
                delivery_assumption=(
                    storage.delivery_assumption.value if storage.delivery_assumption else None
                ),
                overlap_objective_revision=self._manifest_value("overlap_objective_revision"),
                tie_break_profile_revision=self._manifest_value("tie_break_profile_revision"),
                event_order_revision=self._manifest_value("event_order_revision"),
                time_quantization_revision=self._manifest_value("time_quantization_revision"),
                display_format_revision=self._manifest_value("display_format_revision"),
                contact_source=snapshot.contact_source.value,
                synthetic_contact_provider_revision=(
                    None if orbit_derived else snapshot.source_revision_id[:96]
                ),
            )
        )
        station_ids: dict[str, str] = {}
        for station in graph.stations:
            station_id = str(uuid4())
            station_ids[station.stable_key] = station_id
            connection.execute(
                insert(tables.scenario_station).values(
                    id=station_id,
                    scenario_revision_id=revision_id,
                    stable_key=station.stable_key,
                    ground_station_revision_id=revisions[station.ground_station_key],
                    communication_revision_id=revisions[station.communication_key],
                    minimum_elevation_udeg=station.minimum_elevation_udeg,
                    link_compatibility="UNKNOWN",
                    station_preference_rank=station.preference_rank,
                    contact_source=snapshot.contact_source.value,
                )
            )
        payload_ids: dict[str, str] = {}
        for payload in graph.payloads:
            payload_id = str(uuid4())
            payload_ids[payload.stable_key] = payload_id
            connection.execute(
                insert(tables.scenario_payload).values(
                    id=payload_id,
                    scenario_revision_id=revision_id,
                    stable_key=payload.stable_key,
                    payload_type_revision_id=revisions[payload.payload_type_key],
                    display_name=payload.row["display_name"][:160],
                    producer_kind=payload.row["producer_kind"],
                    ready_at=_instant(payload.row["ready_at"]),
                    logical_size_bytes=payload.row["logical_size_bytes"],
                    storage_footprint_bytes=payload.row["storage_footprint_bytes"],
                    service_class=payload.row["service_class"],
                    mission_priority=payload.row["mission_priority"],
                    queue_sequence=payload.row["queue_sequence"],
                    deadline_at=_instant(payload.row["deadline_at"]),
                    deadline_target=payload.row["deadline_target"],
                    post_deadline_action=payload.row["post_deadline_action"],
                    expiry_at=_instant(payload.row["expiry_at"]),
                    severity_rank=payload.row["severity_rank"],
                    bundle_key=payload.row["bundle_key"],
                    bundle_member_role=payload.row["bundle_member_role"],
                    initial_storage_state=payload.row["initial_storage_state"],
                )
            )
        for predecessor, successor, kind in graph.dependencies:
            connection.execute(
                insert(tables.payload_dependency).values(
                    scenario_revision_id=revision_id,
                    predecessor_payload_id=payload_ids[predecessor],
                    successor_payload_id=payload_ids[successor],
                    dependency_kind=kind,
                )
            )
        connection.execute(
            update(tables.scenario_revision)
            .where(tables.scenario_revision.c.id == revision_id)
            .values(
                lifecycle_status="PUBLISHED",
                semantic_hash=revision_hash,
                published_at=datetime.now(UTC),
            )
        )
        connection.execute(
            update(tables.scenario)
            .where(tables.scenario.c.id == scenario_id)
            .values(current_revision_id=revision_id)
        )
        return revision_id, station_ids, payload_ids

    @staticmethod
    def _manifest_value(key: str) -> str:
        from semantix_passbudget.application.service import ENGINE_MANIFEST

        return str(ENGINE_MANIFEST[key])

    def _station_ids(self, connection: Any, revision_id: str) -> dict[str, str]:
        rows = connection.execute(
            select(tables.scenario_station.c.stable_key, tables.scenario_station.c.id).where(
                tables.scenario_station.c.scenario_revision_id == revision_id
            )
        ).fetchall()
        return {str(row[0]): str(row[1]) for row in rows}

    def _payload_ids(self, connection: Any, revision_id: str) -> dict[str, str]:
        rows = connection.execute(
            select(tables.scenario_payload.c.stable_key, tables.scenario_payload.c.id).where(
                tables.scenario_payload.c.scenario_revision_id == revision_id
            )
        ).fetchall()
        return {str(row[0]): str(row[1]) for row in rows}

    def _ensure_snapshot(self, connection: Any, run: StoredRun, revision_id: str) -> str:
        digest = bytes.fromhex(run.input_snapshot_hash)
        existing = connection.execute(
            select(tables.input_snapshot.c.id).where(
                tables.input_snapshot.c.content_sha256 == digest,
                tables.input_snapshot.c.canonicalization_revision == CANONICALIZATION_REVISION,
            )
        ).first()
        if existing is not None:
            return str(existing[0])
        snapshot_id = str(uuid4())
        payload = run.input_snapshot_payload or {}
        connection.execute(
            insert(tables.input_snapshot).values(
                id=snapshot_id,
                scenario_revision_id=revision_id,
                schema_version=run.snapshot.schema_version[:32] if run.snapshot else "unknown",
                json_schema_id=JSON_SCHEMA_ID,
                canonicalization_revision=CANONICALIZATION_REVISION,
                # jsonb cannot take a Fraction or a UtcInstant; the canonical form can.
                canonical_payload=canonical_object(payload),
                canonical_bytes=canonical_bytes(payload),
                content_sha256=digest,
                validation_status="VALID",
                validation_code=None,
            )
        )
        return snapshot_id

    def _ensure_manifest(self, connection: Any, manifest: Mapping[str, Any]) -> str:
        stable_key = f"{manifest['engine_version']}/{manifest['code_revision']}"
        existing = connection.execute(
            select(tables.engine_manifest.c.id).where(
                tables.engine_manifest.c.stable_key == stable_key
            )
        ).first()
        if existing is not None:
            return str(existing[0])
        manifest_id = str(uuid4())
        connection.execute(
            insert(tables.engine_manifest).values(
                id=manifest_id,
                stable_key=stable_key,
                engine_version=manifest["engine_version"],
                code_revision=manifest["code_revision"],
                orbit_provider_revision=manifest["orbit_provider_revision"],
                capacity_engine_revision=manifest["capacity_engine_revision"],
                scheduler_revision=manifest["scheduler_revision"],
                storage_reducer_revision=manifest["storage_reducer_revision"],
                constants_revision=manifest["constants_revision"],
                time_reference_revision=manifest["time_reference_revision"],
                frame_transform_revision=manifest["frame_transform_revision"],
                event_solver_revision=manifest["event_solver_revision"],
                canonicalization_revision=manifest["canonicalization_revision"],
                manifest_sha256=_digest(dict(manifest)),
            )
        )
        return manifest_id

    def _write_run(
        self,
        connection: Any,
        run: StoredRun,
        snapshot_id: str,
        manifest_id: str,
        station_ids: dict[str, str],
        payload_ids: dict[str, str],
    ) -> None:
        requested = datetime.now(UTC)
        connection.execute(
            insert(tables.scenario_run).values(
                id=run.run_id,
                input_snapshot_id=snapshot_id,
                engine_manifest_id=manifest_id,
                status="QUEUED",
                retention_class="STANDARD",
                requested_at=requested,
            )
        )
        connection.execute(
            update(tables.scenario_run)
            .where(tables.scenario_run.c.id == run.run_id)
            .values(status="RUNNING", started_at=requested)
        )
        for stage in run.stages:
            connection.execute(
                insert(tables.run_stage).values(
                    id=str(uuid4()),
                    run_id=run.run_id,
                    stage_code=stage["stage_code"],
                    stage_ordinal=stage["stage_ordinal"],
                    status=stage["status"],
                    started_at=requested,
                    finished_at=requested,
                    produced_row_count=stage["row_count"],
                )
            )
        rows = result_rows(run.result)
        result_ids = self._write_results(connection, run.run_id, rows, station_ids, payload_ids)
        connection.execute(
            update(tables.scenario_run)
            .where(tables.scenario_run.c.id == run.run_id)
            .values(
                status=run.status,
                finished_at=requested,
                terminal_stage_code=run.stages[-1]["stage_code"],
                result_content_hash=bytes.fromhex(run.result_content_hash),
                run_record_hash=bytes.fromhex(run.run_record_hash),
            )
        )
        assert result_ids  # every run writes at least the geometric access rows

    def _write_results(
        self,
        connection: Any,
        run_id: str,
        rows: PersistedRows,
        station_ids: dict[str, str],
        payload_ids: dict[str, str],
    ) -> dict[str, str]:
        result_ids: dict[str, str] = {}
        for row in rows.results:
            result_id = str(uuid4())
            result_ids[str(row["stable_key"])] = result_id
            connection.execute(
                insert(tables.run_result).values(
                    id=result_id,
                    run_id=run_id,
                    stable_key=row["stable_key"],
                    result_kind=row["result_kind"],
                    calculation_status=row["calculation_status"],
                    decision_grade=row["decision_grade"],
                )
            )
        for row in rows.geometric:
            connection.execute(
                insert(tables.geometric_access).values(
                    result_id=result_ids[str(row["stable_key"])],
                    result_kind="GEOMETRIC_ACCESS",
                    scenario_station_id=station_ids[str(row["station_key"])],
                    true_aos=_instant(row["true_aos"]),
                    true_los=_instant(row["true_los"]),
                    clipped_start=_instant(row["clipped_start"]),
                    clipped_end=_instant(row["clipped_end"]),
                    maximum_elevation_udeg=row["maximum_elevation_udeg"],
                    maximum_elevation_at=_instant(row["maximum_elevation_at"]),
                    contact_source=row["contact_source"],
                )
            )
        for row in rows.modeled:
            connection.execute(
                insert(tables.modeled_contact).values(
                    result_id=result_ids[str(row["stable_key"])],
                    result_kind="MODELED_CONTACT",
                    geometric_result_id=result_ids[str(row["geometric_stable_key"])],
                    link_compatibility=row["link_compatibility"],
                    usable_start=_instant(row["usable_start"]),
                    usable_end=_instant(row["usable_end"]),
                    primary_reason_code=row["primary_reason_code"],
                )
            )
        for row in rows.candidates:
            connection.execute(
                insert(tables.candidate_session).values(
                    result_id=result_ids[str(row["stable_key"])],
                    result_kind="CANDIDATE_SESSION",
                    modeled_contact_result_id=result_ids[str(row["modeled_stable_key"])],
                    capacity_bytes=row["capacity_bytes"],
                    conflict_component_key=row["conflict_component_key"],
                )
            )
        for row in rows.scheduled:
            connection.execute(
                insert(tables.scheduled_session).values(
                    result_id=result_ids[str(row["stable_key"])],
                    result_kind="SCHEDULED_SESSION",
                    candidate_result_id=result_ids[str(row["candidate_stable_key"])],
                    selection_ordinal=row["selection_ordinal"],
                    primary_reason_code=row["primary_reason_code"],
                )
            )
        for row in rows.allocations:
            connection.execute(
                insert(tables.transfer_allocation).values(
                    result_id=result_ids[str(row["stable_key"])],
                    result_kind="TRANSFER_ALLOCATION",
                    scheduled_session_result_id=result_ids[
                        str(row["scheduled_session_stable_key"])
                    ],
                    scenario_payload_id=payload_ids[str(row["payload_key"])],
                    allocation_ordinal=row["allocation_ordinal"],
                    logical_offset_start=row["logical_offset_start"],
                    logical_bytes=row["logical_bytes"],
                    started_at=_instant(row["started_at"]),
                    ended_at=_instant(row["ended_at"]),
                    modeled_progress_after_bytes=row["modeled_progress_after_bytes"],
                    modeled_tx_complete_at=_instant(row["modeled_tx_complete_at"]),
                    deadline_status=row["deadline_status"],
                    remaining_after_bytes=row["remaining_after_bytes"],
                    primary_reason_code=row["primary_reason_code"],
                )
            )
        for row in rows.events:
            allocation_key = row["allocation_stable_key"]
            connection.execute(
                insert(tables.run_event).values(
                    result_id=result_ids[str(row["stable_key"])],
                    result_kind="RUN_EVENT",
                    run_id=run_id,
                    event_at=_instant(row["event_at"]),
                    event_order=row["event_order"],
                    event_domain=row["event_domain"],
                    event_kind=row["event_kind"],
                    scenario_payload_id=payload_ids.get(str(row["payload_key"]))
                    if row["payload_key"]
                    else None,
                    allocation_result_id=(
                        result_ids.get(str(allocation_key)) if allocation_key else None
                    ),
                    delta_logical_bytes=row["delta_logical_bytes"],
                    remaining_logical_bytes=row["remaining_logical_bytes"],
                    delta_storage_bytes=row["delta_storage_bytes"],
                    occupancy_bytes=row["occupancy_bytes"],
                    reserve_breach_bytes=row["reserve_breach_bytes"],
                    rejected_bytes=row["rejected_bytes"],
                    reason_code=row["reason_code"],
                )
            )
        for row in rows.metrics:
            connection.execute(
                insert(tables.run_metric).values(
                    result_id=result_ids[str(row["stable_key"])],
                    result_kind="METRIC",
                    metric_code=row["metric_code"],
                    scope_code=row["scope_code"],
                    scenario_station_id=station_ids.get(str(row["station_key"]))
                    if row["station_key"]
                    else None,
                    scenario_payload_id=payload_ids.get(str(row["payload_key"]))
                    if row["payload_key"]
                    else None,
                    unit_code=row["unit_code"],
                    definition_revision=row["definition_revision"],
                    accounting_layer=row["accounting_layer"],
                    value_integer=row["value_integer"],
                )
            )
        for row in rows.annotations:
            subject = row["subject_stable_key"]
            connection.execute(
                insert(tables.run_annotation).values(
                    result_id=result_ids[str(row["stable_key"])],
                    result_kind="ANNOTATION",
                    subject_result_id=result_ids.get(str(subject)) if subject else None,
                    annotation_kind=row["annotation_kind"],
                    code=row["code"],
                    severity=row["severity"],
                    ordinal=row["ordinal"],
                    rule_revision=row["rule_revision"],
                    criterion_code=row["criterion_code"],
                    criterion_value_text=row["criterion_value_text"],
                )
            )
        return result_ids

    # ------------------------------------------------------------------ reading

    def get(self, run_id: str) -> StoredRun | None:
        with _redacted("load run"), self._engine.connect() as connection:
            row = connection.execute(
                select(
                    tables.scenario_run.c.status,
                    tables.scenario_run.c.result_content_hash,
                    tables.scenario_run.c.run_record_hash,
                    tables.scenario_run.c.input_snapshot_id,
                ).where(tables.scenario_run.c.id == run_id)
            ).first()
            if row is None:
                return None
            snapshot_hash = connection.execute(
                select(tables.input_snapshot.c.content_sha256).where(
                    tables.input_snapshot.c.id == row[3]
                )
            ).scalar_one()
            stages = tuple(
                {
                    "stage_code": stage[0],
                    "stage_ordinal": int(stage[1]),
                    "status": stage[2],
                    "row_count": int(stage[3]),
                }
                for stage in connection.execute(
                    select(
                        tables.run_stage.c.stage_code,
                        tables.run_stage.c.stage_ordinal,
                        tables.run_stage.c.status,
                        tables.run_stage.c.produced_row_count,
                    )
                    .where(tables.run_stage.c.run_id == run_id)
                    .order_by(tables.run_stage.c.stage_ordinal)
                ).fetchall()
            )
            rows = self._read_rows(connection, run_id)
            return StoredRun(
                run_id=run_id,
                status=str(row[0]),
                input_snapshot_hash=bytes(snapshot_hash).hex(),
                result_content_hash=bytes(row[1]).hex(),
                run_record_hash=bytes(row[2]).hex(),
                stages=stages,
                result={},
                persisted_rows=rows,
            )

    def _read_rows(self, connection: Any, run_id: str) -> PersistedRows:
        result_rows_by_id: dict[str, dict[str, Any]] = {}
        for row in connection.execute(
            select(
                tables.run_result.c.id,
                tables.run_result.c.stable_key,
                tables.run_result.c.result_kind,
                tables.run_result.c.calculation_status,
                tables.run_result.c.decision_grade,
            ).where(tables.run_result.c.run_id == run_id)
        ).fetchall():
            result_rows_by_id[str(row[0])] = {
                "stable_key": str(row[1]),
                "result_kind": str(row[2]),
                "calculation_status": str(row[3]),
                "decision_grade": str(row[4]) if row[4] is not None else None,
            }
        key_of = {key: value["stable_key"] for key, value in result_rows_by_id.items()}
        ids = list(result_rows_by_id)
        station_key = {
            str(row[0]): str(row[1])
            for row in connection.execute(
                select(tables.scenario_station.c.id, tables.scenario_station.c.stable_key)
            ).fetchall()
        }
        payload_key = {
            str(row[0]): str(row[1])
            for row in connection.execute(
                select(tables.scenario_payload.c.id, tables.scenario_payload.c.stable_key)
            ).fetchall()
        }

        def fetch(table: Any) -> Sequence[Any]:
            rows = connection.execute(select(table).where(table.c.result_id.in_(ids)))
            return list(rows.mappings().fetchall())

        geometric = tuple(
            {
                "stable_key": key_of[str(row["result_id"])],
                "station_key": station_key[str(row["scenario_station_id"])],
                "true_aos": _iso(row["true_aos"]),
                "true_los": _iso(row["true_los"]),
                "clipped_start": _iso(row["clipped_start"]),
                "clipped_end": _iso(row["clipped_end"]),
                "maximum_elevation_udeg": row["maximum_elevation_udeg"],
                "maximum_elevation_at": _iso(row["maximum_elevation_at"]),
                "contact_source": str(row["contact_source"]),
            }
            for row in fetch(tables.geometric_access)
        )
        modeled = tuple(
            {
                "stable_key": key_of[str(row["result_id"])],
                "geometric_stable_key": key_of[str(row["geometric_result_id"])],
                "link_compatibility": str(row["link_compatibility"]),
                "usable_start": _iso(row["usable_start"]),
                "usable_end": _iso(row["usable_end"]),
                "primary_reason_code": row["primary_reason_code"],
            }
            for row in fetch(tables.modeled_contact)
        )
        candidates = tuple(
            {
                "stable_key": key_of[str(row["result_id"])],
                "modeled_stable_key": key_of[str(row["modeled_contact_result_id"])],
                "capacity_bytes": int(row["capacity_bytes"])
                if row["capacity_bytes"] is not None
                else None,
                "conflict_component_key": row["conflict_component_key"],
            }
            for row in fetch(tables.candidate_session)
        )
        scheduled = tuple(
            {
                "stable_key": key_of[str(row["result_id"])],
                "candidate_stable_key": key_of[str(row["candidate_result_id"])],
                "selection_ordinal": int(row["selection_ordinal"]),
                "primary_reason_code": str(row["primary_reason_code"]),
            }
            for row in fetch(tables.scheduled_session)
        )
        allocations = tuple(
            {
                "stable_key": key_of[str(row["result_id"])],
                "scheduled_session_stable_key": key_of[str(row["scheduled_session_result_id"])],
                "payload_key": payload_key[str(row["scenario_payload_id"])],
                "allocation_ordinal": int(row["allocation_ordinal"]),
                "logical_offset_start": int(row["logical_offset_start"]),
                "logical_bytes": int(row["logical_bytes"]),
                "started_at": _iso(row["started_at"]),
                "ended_at": _iso(row["ended_at"]),
                "modeled_progress_after_bytes": int(row["modeled_progress_after_bytes"]),
                "modeled_tx_complete_at": _iso(row["modeled_tx_complete_at"]),
                "deadline_status": row["deadline_status"],
                "remaining_after_bytes": int(row["remaining_after_bytes"]),
                "primary_reason_code": str(row["primary_reason_code"]),
            }
            for row in fetch(tables.transfer_allocation)
        )
        events = tuple(
            {
                "stable_key": key_of[str(row["result_id"])],
                "event_at": _iso(row["event_at"]),
                "event_order": int(row["event_order"]),
                "event_domain": str(row["event_domain"]),
                "event_kind": str(row["event_kind"]),
                "payload_key": payload_key.get(str(row["scenario_payload_id"]))
                if row["scenario_payload_id"]
                else None,
                "allocation_stable_key": key_of.get(str(row["allocation_result_id"]))
                if row["allocation_result_id"]
                else None,
                "delta_logical_bytes": _int(row["delta_logical_bytes"]),
                "remaining_logical_bytes": _int(row["remaining_logical_bytes"]),
                "delta_storage_bytes": _int(row["delta_storage_bytes"]),
                "occupancy_bytes": _int(row["occupancy_bytes"]),
                "reserve_breach_bytes": _int(row["reserve_breach_bytes"]),
                "rejected_bytes": _int(row["rejected_bytes"]),
                "reason_code": str(row["reason_code"]),
            }
            for row in fetch(tables.run_event)
        )
        metrics = tuple(
            {
                "stable_key": key_of[str(row["result_id"])],
                "metric_code": str(row["metric_code"]),
                "scope_code": str(row["scope_code"]),
                "station_key": station_key.get(str(row["scenario_station_id"]))
                if row["scenario_station_id"]
                else None,
                "payload_key": payload_key.get(str(row["scenario_payload_id"]))
                if row["scenario_payload_id"]
                else None,
                "unit_code": str(row["unit_code"]),
                "definition_revision": str(row["definition_revision"]),
                "accounting_layer": row["accounting_layer"],
                "value_integer": _int(row["value_integer"]),
            }
            for row in fetch(tables.run_metric)
        )
        annotations = tuple(
            {
                "stable_key": key_of[str(row["result_id"])],
                "subject_stable_key": key_of.get(str(row["subject_result_id"]))
                if row["subject_result_id"]
                else None,
                "annotation_kind": str(row["annotation_kind"]),
                "code": str(row["code"]),
                "severity": str(row["severity"]),
                "ordinal": int(row["ordinal"]),
                "rule_revision": str(row["rule_revision"]),
                "criterion_code": row["criterion_code"],
                "criterion_value_text": row["criterion_value_text"],
            }
            for row in fetch(tables.run_annotation)
        )
        return PersistedRows(
            results=tuple(result_rows_by_id.values()),
            geometric=geometric,
            modeled=modeled,
            candidates=candidates,
            scheduled=scheduled,
            allocations=allocations,
            events=events,
            metrics=metrics,
            annotations=annotations,
        )


def _int(value: Any) -> int | None:
    return None if value is None else int(value)


def purge_all(engine: Engine) -> None:
    """Delete every row. Only for a disposable test database."""
    order = [
        tables.run_annotation,
        tables.run_metric,
        tables.run_event,
        tables.transfer_allocation,
        tables.scheduled_session,
        tables.candidate_session,
        tables.modeled_contact,
        tables.geometric_access,
    ]
    with engine.begin() as connection:
        for table in order:
            connection.exec_driver_sql(f'DELETE FROM {tables.SCHEMA}."{table.name}"')
        connection.exec_driver_sql("ALTER TABLE passbudget.run_result DISABLE TRIGGER USER")
        connection.execute(delete(tables.run_result))
        connection.exec_driver_sql("ALTER TABLE passbudget.run_result ENABLE TRIGGER USER")
        connection.exec_driver_sql("ALTER TABLE passbudget.run_stage DISABLE TRIGGER USER")
        connection.execute(delete(tables.run_stage))
        connection.exec_driver_sql("ALTER TABLE passbudget.run_stage ENABLE TRIGGER USER")
        connection.exec_driver_sql("ALTER TABLE passbudget.scenario_run DISABLE TRIGGER USER")
        connection.execute(delete(tables.scenario_run))
        connection.exec_driver_sql("ALTER TABLE passbudget.scenario_run ENABLE TRIGGER USER")


__all__ = [
    "AnalysisMode",
    "PersistenceError",
    "PostgresRunRepository",
    "purge_all",
    "replace",
]
