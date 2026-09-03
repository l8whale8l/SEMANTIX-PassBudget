from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from semantix_passbudget.domain.enums import (
    AccountedEffect,
    AdmissionPolicy,
    AnalysisMode,
    BundleMemberRole,
    CapacityProvider,
    ContactSource,
    DeadlineTarget,
    DeliveryAssumption,
    DependencyKind,
    EventOrigin,
    EvidenceState,
    PostDeadlineAction,
    ProducerKind,
    RateScope,
    RateSemantics,
    ReclaimGranularity,
    ReleaseTrigger,
    ReserveEnforcement,
    SegmentationKind,
    ServiceClass,
    StorageMode,
    TransferStartPolicy,
)
from semantix_passbudget.domain.errors import DomainValidationError, ErrorDetail
from semantix_passbudget.domain.models import (
    CapacityProfile,
    ExactRate,
    Payload,
    PayloadDependency,
    RateSegment,
    ScenarioSnapshot,
    Station,
    StorageConfig,
    SyntheticContact,
    SyntheticDeliveryEvent,
    TimeReserve,
)
from semantix_passbudget.domain.time import TimeInterval, UtcInstant


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def enum_field(default: Any = ...) -> Any:
    """Declare an enum field that accepts its canonical ASCII code.

    Strict mode otherwise refuses a plain string for an enum when the body arrives as parsed JSON.
    Matching a declared code exactly is not a lossy coercion, so only enum fields relax strictness;
    integers, byte counts and timestamps stay strict and are never coerced from another type.
    """
    return Field(default, strict=False)


#: Enum inside a container: field-level strictness does not reach list items.
LaxAccountedEffect = Annotated[AccountedEffect, Field(strict=False)]


class IntervalDTO(StrictModel):
    start: str
    end: str

    def to_domain(self, prefix: str) -> TimeInterval:
        return TimeInterval(
            UtcInstant.parse(self.start, f"{prefix}.start"),
            UtcInstant.parse(self.end, f"{prefix}.end"),
        )


class RationalDTO(StrictModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(gt=0)

    def to_fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


class RateSegmentDTO(StrictModel):
    ordinal: int = Field(ge=0)
    start_offset_us: int = Field(ge=0)
    end_offset_us: int = Field(gt=0)
    numerator_bits: int = Field(ge=0)
    denominator_seconds: int = Field(gt=0)

    def to_domain(self) -> RateSegment:
        return RateSegment(
            ordinal=self.ordinal,
            start_offset_us=self.start_offset_us,
            end_offset_us=self.end_offset_us,
            rate=ExactRate(self.numerator_bits, self.denominator_seconds),
        )


class TimeReserveDTO(StrictModel):
    start_offset_us: int = Field(ge=0)
    end_offset_us: int = Field(gt=0)

    def to_domain(self) -> TimeReserve:
        return TimeReserve(self.start_offset_us, self.end_offset_us)


class CapacityDTO(StrictModel):
    provider: CapacityProvider = enum_field()
    rate_semantics: RateSemantics | None = enum_field(None)
    acquisition_guard_us: int = Field(ge=0)
    release_guard_us: int = Field(ge=0)
    rate_segments: list[RateSegmentDTO] = Field(default_factory=list)
    fixed_capacity_bytes: int | None = Field(default=None, ge=0)
    byte_reserve: int = Field(default=0, ge=0)
    active_efficiency: RationalDTO | None = None
    rate_unknown: bool = False
    evidence_state: EvidenceState = enum_field()
    source_revision_id: str | None = None
    rationale: str | None = None
    time_reserves: list[TimeReserveDTO] = Field(default_factory=list)
    measurement_point: str | None = Field(default=None, max_length=96)
    rate_scope: RateScope | None = enum_field(None)
    accounted_effects: list[LaxAccountedEffect] = Field(default_factory=list)

    def to_domain(self) -> CapacityProfile:
        return CapacityProfile(
            provider=self.provider,
            rate_semantics=self.rate_semantics,
            acquisition_guard_us=self.acquisition_guard_us,
            release_guard_us=self.release_guard_us,
            rate_segments=tuple(segment.to_domain() for segment in self.rate_segments),
            fixed_capacity_bytes=self.fixed_capacity_bytes,
            byte_reserve=self.byte_reserve,
            active_efficiency=(
                self.active_efficiency.to_fraction() if self.active_efficiency else None
            ),
            rate_unknown=self.rate_unknown,
            evidence_state=self.evidence_state,
            source_revision_id=self.source_revision_id,
            rationale=self.rationale,
            time_reserves=tuple(item.to_domain() for item in self.time_reserves),
            measurement_point=self.measurement_point,
            rate_scope=self.rate_scope,
            accounted_effects=tuple(self.accounted_effects),
        )


class StationDTO(StrictModel):
    stable_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
    preference_rank: int = Field(ge=0)
    capacity: CapacityDTO

    def to_domain(self) -> Station:
        return Station(self.stable_key, self.preference_rank, self.capacity.to_domain())


class ContactDTO(StrictModel):
    stable_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
    station_key: str
    true_interval: IntervalDTO

    def to_domain(self, index: int) -> SyntheticContact:
        return SyntheticContact(
            self.stable_key,
            self.station_key,
            self.true_interval.to_domain(f"contacts.{index}.true_interval"),
        )


class PayloadDTO(StrictModel):
    stable_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
    logical_size_bytes: int = Field(gt=0)
    storage_size_bytes: int = Field(gt=0)
    ready_at: str
    service_class: ServiceClass = enum_field()
    deadline_at: str | None = None
    deadline_severity: int = Field(ge=0)
    mission_priority: int = Field(ge=0)
    queue_sequence: int = Field(ge=0)
    segmentation: SegmentationKind = enum_field()
    chunk_size_bytes: int | None = Field(default=None, gt=0)
    resume_supported: bool
    deadline_target: DeadlineTarget | None = enum_field(None)
    post_deadline_action: PostDeadlineAction | None = enum_field(None)
    expiry_at: str | None = None
    delete_on_expiry: bool = False
    bundle_key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
    bundle_member_role: BundleMemberRole | None = enum_field(None)
    transfer_start_policy: TransferStartPolicy = enum_field(TransferStartPolicy.ONLY_IF_COMPLETABLE)
    display_name: str | None = Field(default=None, max_length=160)
    media_type: str = Field(default="application/octet-stream", max_length=127)
    producer_kind: ProducerKind = enum_field(ProducerKind.USER_SUPPLIED)

    def to_domain(self, index: int) -> Payload:
        deadline = (
            UtcInstant.parse(self.deadline_at, f"payloads.{index}.deadline_at")
            if self.deadline_at
            else None
        )
        return Payload(
            stable_key=self.stable_key,
            logical_size_bytes=self.logical_size_bytes,
            storage_size_bytes=self.storage_size_bytes,
            ready_at=UtcInstant.parse(self.ready_at, f"payloads.{index}.ready_at"),
            service_class=self.service_class,
            deadline_at=deadline,
            deadline_severity=self.deadline_severity,
            mission_priority=self.mission_priority,
            queue_sequence=self.queue_sequence,
            segmentation=self.segmentation,
            chunk_size_bytes=self.chunk_size_bytes,
            resume_supported=self.resume_supported,
            expiry_at=(
                UtcInstant.parse(self.expiry_at, f"payloads.{index}.expiry_at")
                if self.expiry_at
                else None
            ),
            bundle_key=self.bundle_key,
            bundle_member_role=self.bundle_member_role,
            deadline_target=(
                self.deadline_target
                if deadline is None
                else (self.deadline_target or DeadlineTarget.INSTANCE_COMPLETE)
            ),
            post_deadline_action=(
                self.post_deadline_action
                if deadline is None
                else (self.post_deadline_action or PostDeadlineAction.CONTINUE_AND_REPORT)
            ),
            transfer_start_policy=self.transfer_start_policy,
            delete_on_expiry=self.delete_on_expiry,
            display_name=self.display_name or self.stable_key,
            media_type=self.media_type,
            producer_kind=self.producer_kind,
        )


class StorageDTO(StrictModel):
    mode: StorageMode = enum_field(StorageMode.DISABLED)
    physical_capacity_bytes: int | None = Field(default=None, gt=0)
    reserve_bytes: int = Field(default=0, ge=0)
    initial_occupancy_bytes: int = Field(default=0, ge=0)
    reserve_enforcement: ReserveEnforcement | None = enum_field(None)
    admission_policy: AdmissionPolicy | None = enum_field(None)
    release_trigger: ReleaseTrigger | None = enum_field(None)
    delivery_assumption: DeliveryAssumption | None = enum_field(None)
    reclaim_granularity: ReclaimGranularity | None = enum_field(None)

    def to_domain(self) -> StorageConfig:
        enabled = self.mode is StorageMode.ENABLED
        return StorageConfig(
            mode=self.mode,
            physical_capacity_bytes=self.physical_capacity_bytes,
            reserve_bytes=self.reserve_bytes,
            initial_occupancy_bytes=self.initial_occupancy_bytes,
            reserve_enforcement=self.reserve_enforcement,
            admission_policy=self.admission_policy,
            release_trigger=(self.release_trigger or (ReleaseTrigger.NEVER if enabled else None)),
            delivery_assumption=(
                self.delivery_assumption or (DeliveryAssumption.NONE if enabled else None)
            ),
            reclaim_granularity=(
                self.reclaim_granularity or (ReclaimGranularity.OBJECT if enabled else None)
            ),
        )


class PayloadDependencyDTO(StrictModel):
    predecessor_key: str
    successor_key: str
    kind: DependencyKind = enum_field(DependencyKind.SEND_AFTER)

    def to_domain(self) -> PayloadDependency:
        return PayloadDependency(self.predecessor_key, self.successor_key, self.kind)


class SyntheticDeliveryEventDTO(StrictModel):
    """Test-harness acknowledgement. `event_origin` cannot name a real ground event in P0."""

    payload_key: str
    acknowledged_at: str
    event_origin: EventOrigin = enum_field(EventOrigin.TEST_SYNTHETIC)

    def to_domain(self, index: int) -> SyntheticDeliveryEvent:
        return SyntheticDeliveryEvent(
            payload_key=self.payload_key,
            acknowledged_at=UtcInstant.parse(
                self.acknowledged_at, f"synthetic_delivery_events.{index}.acknowledged_at"
            ),
            event_origin=self.event_origin,
        )


class FixtureDTO(StrictModel):
    schema_version: str
    fixture_id: str
    analysis_mode: AnalysisMode = enum_field()
    analysis_window: IntervalDTO
    stations: list[StationDTO]
    contacts: list[ContactDTO]
    source_revision_id: str
    safety_notice: str
    decision_question: str = Field(default="", max_length=1000)
    policy_revision_id: str | None = None
    payloads: list[PayloadDTO] = Field(default_factory=list)
    dependencies: list[PayloadDependencyDTO] = Field(default_factory=list)
    storage: StorageDTO = Field(default_factory=StorageDTO)
    contact_source: ContactSource = enum_field(ContactSource.SYNTHETIC_INJECTED)
    synthetic_delivery_events: list[SyntheticDeliveryEventDTO] = Field(default_factory=list)

    def to_domain(self) -> ScenarioSnapshot:
        return ScenarioSnapshot(
            schema_version=self.schema_version,
            fixture_id=self.fixture_id,
            analysis_mode=self.analysis_mode,
            analysis_window=self.analysis_window.to_domain("analysis_window"),
            stations=tuple(station.to_domain() for station in self.stations),
            contacts=tuple(contact.to_domain(index) for index, contact in enumerate(self.contacts)),
            source_revision_id=self.source_revision_id,
            safety_notice=self.safety_notice,
            decision_question=self.decision_question,
            policy_revision_id=self.policy_revision_id,
            payloads=tuple(payload.to_domain(index) for index, payload in enumerate(self.payloads)),
            dependencies=tuple(item.to_domain() for item in self.dependencies),
            storage=self.storage.to_domain(),
            contact_source=self.contact_source,
            synthetic_delivery_events=tuple(
                item.to_domain(index) for index, item in enumerate(self.synthetic_delivery_events)
            ),
        )


class CreateRunRequest(StrictModel):
    """A run names exactly one immutable input.

    `snapshot_id` is the specified P0 path. `fixture` and inline `snapshot` remain available for
    the database-free CLI and regression path; all three resolve to the same application service.
    """

    snapshot_id: str | None = None
    fixture: str | None = None
    snapshot: FixtureDTO | None = None

    @model_validator(mode="after")
    def exactly_one_source(self) -> CreateRunRequest:
        provided = sum(item is not None for item in (self.snapshot_id, self.fixture, self.snapshot))
        if provided != 1:
            raise ValueError("provide exactly one of snapshot_id, fixture or snapshot")
        return self


class StageResponse(StrictModel):
    stage_code: str
    stage_ordinal: int
    status: str
    row_count: int


class RunMetadataResponse(StrictModel):
    run_id: str
    status: str
    input_snapshot_hash: str
    result_content_hash: str
    run_record_hash: str
    stages: list[StageResponse]


class RunResultsResponse(StrictModel):
    run_id: str
    input_snapshot_hash: str
    result_content_hash: str
    result: dict[str, Any]


class HealthResponse(StrictModel):
    status: str
    #: Tier name only. Never a path, a URL, a host name or a credential.
    persistence: str = "memory"


class ComparisonRequest(StrictModel):
    baseline_run_id: str
    candidate_run_id: str


PUBLIC_FIXTURE_IDS = (
    "PB-GOLDEN-CORE-01",
    "PB-GOLDEN-QUEUE-01",
    "PB-GOLDEN-OVERLAP-01",
    "PB-GOLDEN-HORIZON-01",
    "PB-GOLDEN-ACK-01",
)


def packaged_fixture_path(fixture_id: str) -> Path:
    if fixture_id not in PUBLIC_FIXTURE_IDS:
        raise DomainValidationError(
            ErrorDetail(
                code="FIXTURE_NOT_FOUND",
                message="The requested public fixture is not available.",
                scope="fixture",
                field_paths=("fixture",),
                affected_branches=(),
            )
        )
    return Path(__file__).resolve().parents[1] / "fixtures" / f"{fixture_id}.json"


def load_fixture(path: Path) -> FixtureDTO:
    return FixtureDTO.model_validate_json(path.read_text(encoding="utf-8"))


def parse_fixture_content(content: dict[str, Any]) -> FixtureDTO:
    """Validate a stored JSON-shaped scenario body.

    The DTOs are strict, so a Python dict holding plain enum *strings* is not accepted directly;
    routing it through the JSON validator keeps one strict contract for stored content, request
    bodies and packaged fixtures alike.
    """
    return FixtureDTO.model_validate_json(json.dumps(content, ensure_ascii=False))


def load_fixture_source(source: str) -> FixtureDTO:
    candidate = Path(source)
    path = candidate if candidate.is_file() else packaged_fixture_path(source)
    return load_fixture(path)


def dto_error_payload(exc: Exception) -> dict[str, Any]:
    return {
        "error": {
            "code": "INVALID_REQUEST",
            "message": str(exc),
            "scope": "request",
            "field_paths": [],
            "affected_branches": [],
            "details": {},
        }
    }
