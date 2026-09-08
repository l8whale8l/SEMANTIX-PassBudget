"""SQLAlchemy Core table definitions for the accepted PostgreSQL schema.

These mirror `db/postgresql/schema_v0_1.sql` plus the `0002_contact_source_provenance`
delta. They are used for parameterised statement construction only: no DDL is emitted from
here and no calculation formula lives in a trigger or an ORM hook. Alembic remains the single
source of schema truth.
"""

from __future__ import annotations

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
)
from sqlalchemy import Enum as _SqlAlchemyEnum
from sqlalchemy.dialects.postgresql import BIGINT, ENUM, JSONB, TIMESTAMP, UUID

SCHEMA = "passbudget"
metadata = MetaData(schema=SCHEMA)


class _ExistingEnum(ENUM):
    """A PostgreSQL enum type that already exists, referenced by name and carried as a string.

    The label set lives in `db/postgresql/` and in the Alembic revisions, and nowhere else.
    Repeating it here would create a second source of schema truth that could drift silently,
    and PostgreSQL already rejects an unknown label on write, which is the check that matters.

    SQLAlchemy's `Enum` is asymmetric when it holds no labels. On the way in,
    `_db_value_for_elem` passes an unrecognised string straight through; on the way out,
    `_object_value_for_elem` raises `LookupError: 'SUCCEEDED' is not among the defined enum
    values ... Possible values: None`. So a labelless reference stores rows happily and then
    fails every read. This type keeps everything else the base class provides -- above all the
    psycopg bind cast, which is what lets `accounted_effect[]` receive a list of strings -- and
    returns the stored label as the plain string the domain uses.
    """

    def result_processor(self, dialect, coltype):  # type: ignore[no-untyped-def]
        # Skip `Enum`'s label lookup; keep whatever `String` does for this dialect.
        return super(_SqlAlchemyEnum, self).result_processor(dialect, coltype)


def _enum(name: str) -> ENUM:
    """Reference an existing PostgreSQL enum type without ever creating or altering it."""
    return _ExistingEnum(name=name, schema=SCHEMA, create_type=False)


_ts = TIMESTAMP(timezone=True)

profile = Table(
    "profile",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("stable_key", String(64), nullable=False, unique=True),
    Column("kind", _enum("profile_kind"), nullable=False),
    Column("name", String(160), nullable=False),
    Column("description", String(1000)),
    Column("is_preset", Boolean, nullable=False, default=False),
    Column("current_revision_id", UUID(as_uuid=False)),
)

profile_revision = Table(
    "profile_revision",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("profile_id", UUID(as_uuid=False), nullable=False),
    Column("profile_kind", _enum("profile_kind"), nullable=False),
    Column("revision_no", Integer, nullable=False),
    Column("lifecycle_status", _enum("revision_status"), nullable=False),
    Column("schema_version", String(32), nullable=False),
    Column("label", String(160), nullable=False),
    Column("change_note", String(1000)),
    Column("based_on_revision_id", UUID(as_uuid=False)),
    Column("semantic_hash", LargeBinary),
    Column("published_at", _ts),
)

orbit_revision = Table(
    "orbit_revision",
    metadata,
    Column("revision_id", UUID(as_uuid=False), primary_key=True),
    Column("profile_kind", _enum("profile_kind"), nullable=False),
    Column("orbit_kind", _enum("orbit_kind"), nullable=False),
    Column("epoch_at", _ts),
    Column("reference_frame", String(32)),
    Column("time_scale", String(16)),
    Column("propagator_revision", String(96)),
    Column("tle_line1", String(69)),
    Column("tle_line2", String(69)),
    Column("tle_provider", String(128)),
    Column("tle_retrieved_at", _ts),
    Column("tle_content_sha256", LargeBinary),
    Column("earth_radius_m", BIGINT),
    Column("altitude_m", BIGINT),
    Column("inclination_udeg", BIGINT),
    Column("raan_udeg", BIGINT),
    Column("argument_of_latitude_udeg", BIGINT),
)

ground_station_revision = Table(
    "ground_station_revision",
    metadata,
    Column("revision_id", UUID(as_uuid=False), primary_key=True),
    Column("profile_kind", _enum("profile_kind"), nullable=False),
    Column("latitude_udeg", BIGINT),
    Column("longitude_udeg", BIGINT),
    Column("ellipsoidal_height_mm", BIGINT),
    Column("rx_resource_key", String(64), nullable=False),
)

communication_revision = Table(
    "communication_revision",
    metadata,
    Column("revision_id", UUID(as_uuid=False), primary_key=True),
    Column("profile_kind", _enum("profile_kind"), nullable=False),
    Column("provider_kind", _enum("capacity_provider_kind"), nullable=False),
    Column("fixed_capacity_bytes", Numeric(20, 0)),
    Column("rate_semantics", _enum("rate_semantics")),
    Column("measurement_point", String(96)),
    Column("rate_scope", _enum("rate_scope")),
    Column("accounted_effects", ARRAY(_enum("accounted_effect")), nullable=False),
    Column("acquisition_guard_us", BIGINT, nullable=False),
    Column("release_guard_us", BIGINT, nullable=False),
    Column("reserve_kind", _enum("reserve_kind"), nullable=False),
    Column("reserve_bytes", Numeric(20, 0)),
    Column("capacity_accounting_layer", String(32), nullable=False),
)

communication_timeline_segment = Table(
    "communication_timeline_segment",
    metadata,
    Column("revision_id", UUID(as_uuid=False), primary_key=True),
    Column("segment_kind", _enum("communication_segment_kind"), primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("start_offset_us", BIGINT, nullable=False),
    Column("end_offset_us", BIGINT),
    Column("rate_numerator_bits", Numeric(39, 0)),
    Column("rate_denominator_seconds", Numeric(39, 0)),
)

payload_type_revision = Table(
    "payload_type_revision",
    metadata,
    Column("revision_id", UUID(as_uuid=False), primary_key=True),
    Column("profile_kind", _enum("profile_kind"), nullable=False),
    Column("media_type", String(127), nullable=False),
    Column("serializer_revision", String(96), nullable=False),
    Column("segmentation", _enum("segmentation_kind"), nullable=False),
    Column("fixed_chunk_bytes", Numeric(20, 0)),
    Column("resume_allowed", Boolean, nullable=False),
    Column("partial_product_usable", Boolean, nullable=False),
    Column("completion_rule_revision", String(96), nullable=False),
)

policy_revision = Table(
    "policy_revision",
    metadata,
    Column("revision_id", UUID(as_uuid=False), primary_key=True),
    Column("profile_kind", _enum("profile_kind"), nullable=False),
    Column("policy_kind", _enum("policy_kind"), nullable=False),
    Column("comparator_revision", String(96), nullable=False),
    Column("objective_revision", String(96), nullable=False),
    Column("tie_break_revision", String(96), nullable=False),
    Column("starvation_guard", _enum("starvation_guard_mode"), nullable=False),
    Column("max_wait_us", BIGINT),
    Column("value_model_revision", String(96)),
)

scenario = Table(
    "scenario",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("stable_key", String(64), nullable=False, unique=True),
    Column("name", String(160), nullable=False),
    Column("description", String(1000)),
    Column("is_preset", Boolean, nullable=False),
    Column("current_revision_id", UUID(as_uuid=False)),
)

scenario_revision = Table(
    "scenario_revision",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("scenario_id", UUID(as_uuid=False), nullable=False),
    Column("revision_no", Integer, nullable=False),
    Column("lifecycle_status", _enum("revision_status"), nullable=False),
    Column("schema_version", String(32), nullable=False),
    Column("based_on_revision_id", UUID(as_uuid=False)),
    Column("decision_question", String(1000), nullable=False),
    Column("analysis_start", _ts, nullable=False),
    Column("analysis_end", _ts, nullable=False),
    Column("analysis_mode", _enum("analysis_mode"), nullable=False),
    Column("spacecraft_revision_id", UUID(as_uuid=False), nullable=False),
    Column("spacecraft_profile_kind", _enum("profile_kind"), nullable=False),
    Column("orbit_revision_id", UUID(as_uuid=False)),
    Column("policy_revision_id", UUID(as_uuid=False)),
    Column("storage_mode", _enum("storage_model_mode"), nullable=False),
    Column("physical_capacity_bytes", Numeric(20, 0)),
    Column("protected_reserve_bytes", Numeric(20, 0)),
    Column("initial_nonqueue_bytes", Numeric(20, 0)),
    Column("reserve_enforcement", _enum("reserve_enforcement")),
    Column("storage_admission_policy", _enum("storage_admission_policy")),
    Column("reclaim_granularity", _enum("reclaim_granularity")),
    Column("release_trigger", _enum("release_trigger")),
    Column("delivery_assumption", _enum("delivery_assumption")),
    Column("overlap_objective_revision", String(96), nullable=False),
    Column("tie_break_profile_revision", String(96), nullable=False),
    Column("event_order_revision", String(96), nullable=False),
    Column("time_quantization_revision", String(96), nullable=False),
    Column("display_format_revision", String(96), nullable=False),
    Column("semantic_hash", LargeBinary),
    Column("change_note", String(1000)),
    Column("published_at", _ts),
    Column("contact_source", _enum("contact_source_kind"), nullable=False),
    Column("synthetic_contact_provider_revision", String(96)),
)

scenario_station = Table(
    "scenario_station",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("scenario_revision_id", UUID(as_uuid=False), nullable=False),
    Column("stable_key", String(64), nullable=False),
    Column("ground_station_revision_id", UUID(as_uuid=False), nullable=False),
    Column("communication_revision_id", UUID(as_uuid=False)),
    Column("minimum_elevation_udeg", BIGINT),
    Column("link_compatibility", _enum("compatibility_status"), nullable=False),
    Column("station_preference_rank", Integer),
    Column("contact_source", _enum("contact_source_kind"), nullable=False),
)

scenario_payload = Table(
    "scenario_payload",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("scenario_revision_id", UUID(as_uuid=False), nullable=False),
    Column("stable_key", String(64), nullable=False),
    Column("payload_type_revision_id", UUID(as_uuid=False), nullable=False),
    Column("display_name", String(160), nullable=False),
    Column("producer_kind", _enum("producer_kind"), nullable=False),
    Column("ready_at", _ts, nullable=False),
    Column("logical_size_bytes", Numeric(20, 0)),
    Column("storage_footprint_bytes", Numeric(20, 0)),
    Column("service_class", _enum("service_class"), nullable=False),
    Column("mission_priority", SmallInteger, nullable=False),
    Column("queue_sequence", BIGINT, nullable=False),
    Column("deadline_at", _ts),
    Column("deadline_target", _enum("deadline_target")),
    Column("post_deadline_action", _enum("post_deadline_action")),
    Column("expiry_at", _ts),
    Column("severity_rank", SmallInteger),
    Column("bundle_key", String(64)),
    Column("bundle_member_role", _enum("bundle_member_role")),
    Column("initial_storage_state", _enum("initial_storage_state"), nullable=False),
)

payload_dependency = Table(
    "payload_dependency",
    metadata,
    Column("scenario_revision_id", UUID(as_uuid=False), primary_key=True),
    Column("predecessor_payload_id", UUID(as_uuid=False), primary_key=True),
    Column("successor_payload_id", UUID(as_uuid=False), primary_key=True),
    Column("dependency_kind", _enum("dependency_kind"), primary_key=True),
)

engine_manifest = Table(
    "engine_manifest",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("stable_key", String(96), nullable=False, unique=True),
    Column("engine_version", String(96), nullable=False),
    Column("code_revision", String(96), nullable=False),
    Column("orbit_provider_revision", String(96), nullable=False),
    Column("capacity_engine_revision", String(96), nullable=False),
    Column("scheduler_revision", String(96), nullable=False),
    Column("storage_reducer_revision", String(96), nullable=False),
    Column("constants_revision", String(96), nullable=False),
    Column("time_reference_revision", String(96), nullable=False),
    Column("frame_transform_revision", String(96), nullable=False),
    Column("event_solver_revision", String(96), nullable=False),
    Column("canonicalization_revision", String(96), nullable=False),
    Column("manifest_sha256", LargeBinary, nullable=False),
)

input_snapshot = Table(
    "input_snapshot",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("scenario_revision_id", UUID(as_uuid=False), nullable=False),
    Column("schema_version", String(32), nullable=False),
    Column("json_schema_id", String(128), nullable=False),
    Column("canonicalization_revision", String(96), nullable=False),
    Column("canonical_payload", JSONB, nullable=False),
    Column("canonical_bytes", LargeBinary, nullable=False),
    Column("content_sha256", LargeBinary, nullable=False),
    Column("validation_status", _enum("snapshot_validation_status"), nullable=False),
    Column("validation_code", String(96)),
)

scenario_run = Table(
    "scenario_run",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("input_snapshot_id", UUID(as_uuid=False), nullable=False),
    Column("engine_manifest_id", UUID(as_uuid=False), nullable=False),
    Column("replay_of_run_id", UUID(as_uuid=False)),
    Column("status", _enum("run_status"), nullable=False),
    Column("retention_class", _enum("retention_class"), nullable=False),
    Column("requested_at", _ts, nullable=False),
    Column("started_at", _ts),
    Column("finished_at", _ts),
    Column("terminal_stage_code", String(64)),
    Column("error_code", String(96)),
    Column("result_content_hash", LargeBinary),
    Column("run_record_hash", LargeBinary),
)

run_stage = Table(
    "run_stage",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("run_id", UUID(as_uuid=False), nullable=False),
    Column("stage_code", String(64), nullable=False),
    Column("stage_ordinal", SmallInteger, nullable=False),
    Column("status", _enum("stage_status"), nullable=False),
    Column("started_at", _ts),
    Column("finished_at", _ts),
    Column("produced_row_count", BIGINT),
    Column("error_code", String(96)),
)

run_result = Table(
    "run_result",
    metadata,
    Column("id", UUID(as_uuid=False), primary_key=True),
    Column("run_id", UUID(as_uuid=False), nullable=False),
    Column("stable_key", String(128), nullable=False),
    Column("result_kind", _enum("result_kind"), nullable=False),
    Column("calculation_status", _enum("calculation_status"), nullable=False),
    Column("decision_grade", _enum("decision_grade")),
)

geometric_access = Table(
    "geometric_access",
    metadata,
    Column("result_id", UUID(as_uuid=False), primary_key=True),
    Column("result_kind", _enum("result_kind"), nullable=False),
    Column("scenario_station_id", UUID(as_uuid=False), nullable=False),
    Column("true_aos", _ts, nullable=False),
    Column("true_los", _ts, nullable=False),
    Column("clipped_start", _ts, nullable=False),
    Column("clipped_end", _ts, nullable=False),
    Column("maximum_elevation_udeg", BIGINT),
    Column("maximum_elevation_at", _ts),
    Column("contact_source", _enum("contact_source_kind"), nullable=False),
)

modeled_contact = Table(
    "modeled_contact",
    metadata,
    Column("result_id", UUID(as_uuid=False), primary_key=True),
    Column("result_kind", _enum("result_kind"), nullable=False),
    Column("geometric_result_id", UUID(as_uuid=False), nullable=False),
    Column("link_compatibility", _enum("compatibility_status"), nullable=False),
    Column("usable_start", _ts),
    Column("usable_end", _ts),
    Column("primary_reason_code", String(96)),
)

candidate_session = Table(
    "candidate_session",
    metadata,
    Column("result_id", UUID(as_uuid=False), primary_key=True),
    Column("result_kind", _enum("result_kind"), nullable=False),
    Column("modeled_contact_result_id", UUID(as_uuid=False), nullable=False),
    Column("capacity_bytes", Numeric(20, 0)),
    Column("conflict_component_key", String(96)),
)

scheduled_session = Table(
    "scheduled_session",
    metadata,
    Column("result_id", UUID(as_uuid=False), primary_key=True),
    Column("result_kind", _enum("result_kind"), nullable=False),
    Column("candidate_result_id", UUID(as_uuid=False), nullable=False),
    Column("selection_ordinal", Integer, nullable=False),
    Column("primary_reason_code", String(96), nullable=False),
)

transfer_allocation = Table(
    "transfer_allocation",
    metadata,
    Column("result_id", UUID(as_uuid=False), primary_key=True),
    Column("result_kind", _enum("result_kind"), nullable=False),
    Column("scheduled_session_result_id", UUID(as_uuid=False), nullable=False),
    Column("scenario_payload_id", UUID(as_uuid=False), nullable=False),
    Column("allocation_ordinal", Integer, nullable=False),
    Column("logical_offset_start", Numeric(20, 0), nullable=False),
    Column("logical_bytes", Numeric(20, 0), nullable=False),
    Column("started_at", _ts, nullable=False),
    Column("ended_at", _ts, nullable=False),
    Column("modeled_progress_after_bytes", Numeric(20, 0), nullable=False),
    Column("modeled_tx_complete_at", _ts),
    Column("deadline_status", String(32)),
    Column("remaining_after_bytes", Numeric(20, 0), nullable=False),
    Column("primary_reason_code", String(96), nullable=False),
)

run_event = Table(
    "run_event",
    metadata,
    Column("result_id", UUID(as_uuid=False), primary_key=True),
    Column("result_kind", _enum("result_kind"), nullable=False),
    Column("run_id", UUID(as_uuid=False), nullable=False),
    Column("event_at", _ts, nullable=False),
    Column("event_order", Integer, nullable=False),
    Column("event_domain", _enum("event_domain"), nullable=False),
    Column("event_kind", String(64), nullable=False),
    Column("scenario_payload_id", UUID(as_uuid=False)),
    Column("allocation_result_id", UUID(as_uuid=False)),
    Column("delta_logical_bytes", Numeric(20, 0)),
    Column("remaining_logical_bytes", Numeric(20, 0)),
    Column("delta_storage_bytes", Numeric(20, 0)),
    Column("occupancy_bytes", Numeric(20, 0)),
    Column("reserve_breach_bytes", Numeric(20, 0)),
    Column("rejected_bytes", Numeric(20, 0)),
    Column("reason_code", String(96), nullable=False),
)

run_metric = Table(
    "run_metric",
    metadata,
    Column("result_id", UUID(as_uuid=False), primary_key=True),
    Column("result_kind", _enum("result_kind"), nullable=False),
    Column("metric_code", String(96), nullable=False),
    Column("scope_code", String(64), nullable=False),
    Column("scenario_station_id", UUID(as_uuid=False)),
    Column("scenario_payload_id", UUID(as_uuid=False)),
    Column("unit_code", String(32), nullable=False),
    Column("definition_revision", String(96), nullable=False),
    Column("accounting_layer", String(32)),
    Column("value_integer", Numeric(39, 0)),
)

run_annotation = Table(
    "run_annotation",
    metadata,
    Column("result_id", UUID(as_uuid=False), primary_key=True),
    Column("result_kind", _enum("result_kind"), nullable=False),
    Column("subject_result_id", UUID(as_uuid=False)),
    Column("annotation_kind", _enum("annotation_kind"), nullable=False),
    Column("code", String(96), nullable=False),
    Column("severity", _enum("annotation_severity"), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("rule_revision", String(96), nullable=False),
    Column("compared_result_id", UUID(as_uuid=False)),
    Column("criterion_code", String(96)),
    Column("criterion_value_integer", Numeric(39, 0)),
    Column("criterion_value_text", String(256)),
    Column("unit_code", String(32)),
    Column("message", String(1000)),
)

__all__ = [
    "ARRAY",
    "SCHEMA",
    "CheckConstraint",
    "ForeignKey",
    "Text",
    "candidate_session",
    "communication_revision",
    "communication_timeline_segment",
    "engine_manifest",
    "geometric_access",
    "ground_station_revision",
    "input_snapshot",
    "metadata",
    "modeled_contact",
    "payload_dependency",
    "payload_type_revision",
    "policy_revision",
    "profile",
    "profile_revision",
    "run_annotation",
    "run_event",
    "run_metric",
    "run_result",
    "run_stage",
    "scenario",
    "scenario_payload",
    "scenario_revision",
    "scenario_run",
    "scenario_station",
    "scheduled_session",
    "transfer_allocation",
]
