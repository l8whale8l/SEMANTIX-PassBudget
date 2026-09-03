from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import pairwise
from typing import cast

from .enums import (
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
from .errors import DomainValidationError, ErrorDetail
from .time import TimeInterval, UtcInstant


@dataclass(frozen=True, slots=True)
class ExactRate:
    numerator_bits: int
    denominator_seconds: int

    def __post_init__(self) -> None:
        if self.numerator_bits < 0 or self.denominator_seconds <= 0:
            raise DomainValidationError(
                ErrorDetail(
                    code="INVALID_EXACT_RATE",
                    message="Exact rate requires a nonnegative numerator and positive denominator.",
                    scope="capacity",
                    field_paths=("rate.numerator_bits", "rate.denominator_seconds"),
                    affected_branches=("capacity", "schedule"),
                )
            )

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.numerator_bits, self.denominator_seconds)


@dataclass(frozen=True, slots=True)
class RateSegment:
    ordinal: int
    start_offset_us: int
    end_offset_us: int
    rate: ExactRate

    def __post_init__(self) -> None:
        if (
            self.ordinal < 0
            or self.start_offset_us < 0
            or self.start_offset_us >= self.end_offset_us
        ):
            raise DomainValidationError(
                ErrorDetail(
                    code="INVALID_RATE_SEGMENT",
                    message="Rate segment offsets must form a positive [start,end) interval.",
                    scope="capacity",
                    field_paths=("rate_segments",),
                    affected_branches=("capacity", "schedule"),
                )
            )


@dataclass(frozen=True, slots=True)
class TimeReserve:
    start_offset_us: int
    end_offset_us: int

    def __post_init__(self) -> None:
        if self.start_offset_us < 0 or self.start_offset_us >= self.end_offset_us:
            raise DomainValidationError(
                ErrorDetail(
                    code="INVALID_TIME_RESERVE",
                    message="Time reserve requires a positive [start,end) offset interval.",
                    scope="capacity",
                    field_paths=("capacity.time_reserves",),
                    affected_branches=("capacity", "schedule"),
                )
            )


@dataclass(frozen=True, slots=True)
class CapacityProfile:
    provider: CapacityProvider
    rate_semantics: RateSemantics | None
    acquisition_guard_us: int
    release_guard_us: int
    rate_segments: tuple[RateSegment, ...]
    fixed_capacity_bytes: int | None
    byte_reserve: int
    active_efficiency: Fraction | None
    rate_unknown: bool
    evidence_state: EvidenceState
    source_revision_id: str | None
    rationale: str | None
    time_reserves: tuple[TimeReserve, ...] = ()
    measurement_point: str | None = None
    rate_scope: RateScope | None = None
    accounted_effects: tuple[AccountedEffect, ...] = ()

    def validate(self) -> None:
        if self.acquisition_guard_us < 0 or self.release_guard_us < 0 or self.byte_reserve < 0:
            self._invalid("INVALID_CAPACITY_INPUT", "Guard and reserve values must be nonnegative.")
        if self.evidence_state is EvidenceState.PROXY and (
            not self.source_revision_id or not self.rationale
        ):
            self._invalid(
                "INVALID_EVIDENCE_COMBINATION",
                "PROXY capacity requires a source revision and substitution rationale.",
            )
        if self.provider is CapacityProvider.FIXED_RATE:
            if self.fixed_capacity_bytes is not None:
                self._conflict()
            if self.rate_semantics is None:
                self._invalid("MISSING_RATE_SEMANTICS", "FIXED_RATE requires rate semantics.")
            if not self.measurement_point or self.rate_scope is None:
                self._invalid(
                    "MISSING_RATE_MEASUREMENT_CONTRACT",
                    "FIXED_RATE requires an explicit measurement point and rate scope.",
                )
            if len(set(self.accounted_effects)) != len(self.accounted_effects):
                self._invalid(
                    "INVALID_ACCOUNTED_EFFECTS",
                    "Accounted effects must be a set of distinct effects.",
                )
            if (
                self.rate_semantics is RateSemantics.APPLICATION_GOODPUT
                and self.active_efficiency is not None
            ):
                self._conflict()
            if self.rate_unknown and self.rate_segments:
                self._invalid(
                    "INVALID_RATE_SEGMENTS", "UNKNOWN rate cannot also provide rate segments."
                )
            if not self.rate_unknown and not self.rate_segments:
                self._invalid(
                    "MISSING_RATE_SEGMENTS", "FIXED_RATE requires rate segments or UNKNOWN."
                )
            ordered = sorted(self.rate_segments, key=lambda item: item.ordinal)
            if ordered and (
                ordered[0].start_offset_us != 0
                or len({item.ordinal for item in ordered}) != len(ordered)
                or any(
                    left.end_offset_us != right.start_offset_us for left, right in pairwise(ordered)
                )
            ):
                self._invalid(
                    "INVALID_RATE_SEGMENTS",
                    "Rate segments require unique ordinals and contiguous, "
                    "non-overlapping coverage.",
                )
            reserves = sorted(self.time_reserves, key=lambda item: item.start_offset_us)
            if any(
                left.end_offset_us > right.start_offset_us for left, right in pairwise(reserves)
            ):
                self._invalid(
                    "INVALID_TIME_RESERVE",
                    "Time reserves must not overlap.",
                )
        else:
            if self.fixed_capacity_bytes is None or self.fixed_capacity_bytes < 0:
                self._invalid(
                    "INVALID_FIXED_CAPACITY",
                    "Fixed capacity requires a nonnegative integer byte value.",
                )
            if (
                self.rate_segments
                or self.time_reserves
                or self.byte_reserve
                or self.active_efficiency is not None
            ):
                self._conflict()
            if (
                self.rate_semantics is not None
                or self.measurement_point is not None
                or self.rate_scope is not None
                or self.accounted_effects
            ):
                self._conflict()

    @staticmethod
    def _invalid(code: str, message: str) -> None:
        raise DomainValidationError(
            ErrorDetail(
                code=code,
                message=message,
                scope="communication_revision",
                field_paths=("capacity",),
                affected_branches=("capacity", "schedule"),
            )
        )

    @staticmethod
    def _conflict() -> None:
        raise DomainValidationError(
            ErrorDetail(
                code="INPUT_FACTOR_CONFLICT",
                message="Fixed rate and final per-contact capacity inputs are mutually exclusive.",
                scope="communication_revision",
                field_paths=("capacity.rate_segments", "capacity.fixed_capacity_bytes"),
                affected_branches=("capacity", "schedule"),
            )
        )


@dataclass(frozen=True, slots=True)
class Station:
    stable_key: str
    preference_rank: int
    capacity: CapacityProfile


@dataclass(frozen=True, slots=True)
class SyntheticContact:
    stable_key: str
    station_key: str
    true_interval: TimeInterval


@dataclass(frozen=True, slots=True)
class Payload:
    stable_key: str
    logical_size_bytes: int
    storage_size_bytes: int
    ready_at: UtcInstant
    service_class: ServiceClass
    deadline_at: UtcInstant | None
    deadline_severity: int
    mission_priority: int
    queue_sequence: int
    segmentation: SegmentationKind
    chunk_size_bytes: int | None
    resume_supported: bool
    expiry_at: UtcInstant | None = None
    bundle_key: str | None = None
    bundle_member_role: BundleMemberRole | None = None
    deadline_target: DeadlineTarget | None = None
    post_deadline_action: PostDeadlineAction | None = None
    transfer_start_policy: TransferStartPolicy = TransferStartPolicy.ONLY_IF_COMPLETABLE
    delete_on_expiry: bool = False
    display_name: str = ""
    #: Not a calculation input. DEFAULTED when the caller does not declare one.
    media_type: str = "application/octet-stream"
    producer_kind: ProducerKind = ProducerKind.USER_SUPPLIED

    def validate(self) -> None:
        if self.logical_size_bytes <= 0 or self.storage_size_bytes <= 0:
            self._invalid("Payload sizes must be positive integer byte values.")
        if self.deadline_severity < 0 or self.mission_priority < 0 or self.queue_sequence < 0:
            self._invalid("Queue comparator values must be nonnegative integers.")
        if (self.deadline_at is None) != (self.deadline_target is None) or (
            self.deadline_at is None
        ) != (self.post_deadline_action is None):
            self._invalid("A deadline requires both a target event and a post-deadline action.")
        if self.expiry_at is not None and self.expiry_at <= self.ready_at:
            self._invalid("Expiry uses [ready_at, expiry_at) and requires ready_at < expiry_at.")
        if (self.bundle_key is None) != (self.bundle_member_role is None):
            self._invalid("A bundle member requires both a bundle key and a member role.")
        if self.delete_on_expiry:
            self._invalid("P0 fixes delete_on_expiry to false; expiry never deletes an object.")
        if not 0 <= self.mission_priority <= 100 or not 0 <= self.deadline_severity <= 100:
            self._invalid("mission_priority and deadline_severity are bounded to 0..100.")
        if self.segmentation is SegmentationKind.FIXED_CHUNK:
            if self.chunk_size_bytes is None or self.chunk_size_bytes <= 0:
                self._invalid("FIXED_CHUNK requires a positive chunk size.")
            if not self.resume_supported:
                self._invalid("FIXED_CHUNK requires resumable transfer in P0.")
        elif self.chunk_size_bytes is not None or self.resume_supported:
            self._invalid("ATOMIC_OBJECT cannot declare chunking or resume support.")

    def _invalid(self, message: str) -> None:
        raise DomainValidationError(
            ErrorDetail(
                code="INVALID_PAYLOAD",
                message=message,
                scope="queue",
                field_paths=(f"payloads.{self.stable_key}",),
                affected_branches=("schedule", "storage"),
            )
        )


@dataclass(frozen=True, slots=True)
class StorageConfig:
    mode: StorageMode
    physical_capacity_bytes: int | None
    reserve_bytes: int
    initial_occupancy_bytes: int
    reserve_enforcement: ReserveEnforcement | None
    admission_policy: AdmissionPolicy | None
    release_trigger: ReleaseTrigger | None = None
    delivery_assumption: DeliveryAssumption | None = None
    reclaim_granularity: ReclaimGranularity | None = None

    def validate(self) -> None:
        if self.mode is StorageMode.DISABLED:
            if (
                any(
                    value is not None
                    for value in (
                        self.physical_capacity_bytes,
                        self.reserve_enforcement,
                        self.admission_policy,
                        self.release_trigger,
                        self.delivery_assumption,
                        self.reclaim_granularity,
                    )
                )
                or self.reserve_bytes
                or self.initial_occupancy_bytes
            ):
                self._invalid("DISABLED storage cannot carry capacity or policy values.")
            return
        if self.physical_capacity_bytes is None or self.physical_capacity_bytes <= 0:
            self._invalid("ENABLED storage requires positive physical capacity.")
        if self.reserve_bytes < 0 or self.initial_occupancy_bytes < 0:
            self._invalid("Storage reserve and initial occupancy must be nonnegative.")
        assert self.physical_capacity_bytes is not None
        if self.reserve_bytes > self.physical_capacity_bytes:
            self._invalid("Protected reserve cannot exceed physical capacity.")
        if self.initial_occupancy_bytes > self.physical_capacity_bytes:
            self._invalid("Initial occupancy cannot exceed physical capacity.")
        if self.reserve_enforcement is None or self.admission_policy is None:
            self._invalid("ENABLED storage requires reserve and admission policies.")
        if self.reclaim_granularity is None:
            self._invalid("ENABLED storage requires an explicit reclaim granularity.")
        trigger = self.release_trigger
        assumption = self.delivery_assumption
        if trigger is None or assumption is None:
            self._invalid("ENABLED storage requires a release trigger and delivery assumption.")
        allowed = {
            ReleaseTrigger.NEVER: DeliveryAssumption.NONE,
            ReleaseTrigger.TX_END: DeliveryAssumption.TX_END_EQUALS_DELIVERED,
            ReleaseTrigger.ACKED: DeliveryAssumption.NONE,
        }
        if allowed[cast(ReleaseTrigger, trigger)] is not assumption:
            self._invalid(
                "release_trigger and delivery_assumption must agree: NEVER/ACKED require NONE and "
                "TX_END requires the TX_END_EQUALS_DELIVERED proxy."
            )

    @property
    def usable_limit_bytes(self) -> int:
        assert self.physical_capacity_bytes is not None
        return self.physical_capacity_bytes - self.reserve_bytes

    @staticmethod
    def _invalid(message: str) -> None:
        raise DomainValidationError(
            ErrorDetail(
                code="INVALID_STORAGE_CONFIG",
                message=message,
                scope="storage",
                field_paths=("storage",),
                affected_branches=("storage", "schedule"),
            )
        )


@dataclass(frozen=True, slots=True)
class PayloadDependency:
    predecessor_key: str
    successor_key: str
    kind: DependencyKind


@dataclass(frozen=True, slots=True)
class SyntheticDeliveryEvent:
    """Test-harness-only delivery acknowledgement.

    P0 has no real ACK ingest. `event_origin` is fixed to TEST_SYNTHETIC so no user-facing
    result can claim that a ground station acknowledged anything.
    """

    payload_key: str
    acknowledged_at: UtcInstant
    event_origin: EventOrigin = EventOrigin.TEST_SYNTHETIC


DISABLED_STORAGE = StorageConfig(
    mode=StorageMode.DISABLED,
    physical_capacity_bytes=None,
    reserve_bytes=0,
    initial_occupancy_bytes=0,
    reserve_enforcement=None,
    admission_policy=None,
)


@dataclass(frozen=True, slots=True)
class ScenarioSnapshot:
    schema_version: str
    fixture_id: str
    analysis_mode: AnalysisMode
    analysis_window: TimeInterval
    stations: tuple[Station, ...]
    contacts: tuple[SyntheticContact, ...]
    source_revision_id: str
    safety_notice: str
    decision_question: str = ""
    policy_revision_id: str | None = None
    payloads: tuple[Payload, ...] = ()
    dependencies: tuple[PayloadDependency, ...] = ()
    storage: StorageConfig = DISABLED_STORAGE
    contact_source: ContactSource = ContactSource.SYNTHETIC_INJECTED
    synthetic_delivery_events: tuple[SyntheticDeliveryEvent, ...] = ()

    def validate(self) -> None:
        if self.analysis_mode is AnalysisMode.NETWORK_ONLY and (
            self.payloads
            or self.policy_revision_id is not None
            or self.storage.mode is not StorageMode.DISABLED
        ):
            raise DomainValidationError(
                ErrorDetail(
                    code="NETWORK_ONLY_INPUT_CONFLICT",
                    message="NETWORK_ONLY excludes queue policy, payload, and storage inputs.",
                    scope="scenario",
                    field_paths=("analysis_mode", "payloads", "storage"),
                    affected_branches=("schedule",),
                )
            )
        if self.analysis_mode is AnalysisMode.QUEUE_AWARE and (
            not self.policy_revision_id or not self.payloads
        ):
            raise DomainValidationError(
                ErrorDetail(
                    code="MISSING_QUEUE_INPUT",
                    message="QUEUE_AWARE requires a literal policy revision and payload manifest.",
                    scope="scenario",
                    field_paths=("policy_revision_id", "payloads"),
                    affected_branches=("schedule",),
                )
            )
        if not self.decision_question.strip():
            raise DomainValidationError(
                ErrorDetail(
                    code="MISSING_DECISION_QUESTION",
                    message="Every scenario revision states the decision question it answers.",
                    scope="scenario",
                    field_paths=("decision_question",),
                    affected_branches=(),
                )
            )
        station_keys = {station.stable_key for station in self.stations}
        if not station_keys or len(station_keys) != len(self.stations):
            raise DomainValidationError(
                ErrorDetail(
                    code="INVALID_STATION_SET",
                    message="At least one uniquely keyed station is required.",
                    scope="scenario",
                    field_paths=("stations",),
                    affected_branches=("contact", "capacity", "schedule"),
                )
            )
        for station in self.stations:
            station.capacity.validate()
        payload_keys = {payload.stable_key for payload in self.payloads}
        if len(payload_keys) != len(self.payloads):
            raise DomainValidationError(
                ErrorDetail(
                    code="DUPLICATE_PAYLOAD_KEY",
                    message="Payload stable keys must be unique.",
                    scope="queue",
                    field_paths=("payloads.stable_key",),
                    affected_branches=("schedule", "storage"),
                )
            )
        for payload in self.payloads:
            payload.validate()
        edges: dict[str, set[str]] = {key: set() for key in payload_keys}
        indegree = {key: 0 for key in payload_keys}
        for dependency in self.dependencies:
            if (
                dependency.predecessor_key not in payload_keys
                or dependency.successor_key not in payload_keys
            ):
                raise DomainValidationError(
                    ErrorDetail(
                        code="UNKNOWN_PAYLOAD_DEPENDENCY",
                        message="Dependencies must reference declared payloads.",
                        scope="queue",
                        field_paths=("dependencies",),
                        affected_branches=("schedule",),
                    )
                )
            if dependency.successor_key not in edges[dependency.predecessor_key]:
                edges[dependency.predecessor_key].add(dependency.successor_key)
                indegree[dependency.successor_key] += 1
        frontier = sorted(key for key, count in indegree.items() if count == 0)
        visited = 0
        while frontier:
            key = frontier.pop(0)
            visited += 1
            for successor in sorted(edges[key]):
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    frontier.append(successor)
                    frontier.sort()
        if visited != len(payload_keys):
            raise DomainValidationError(
                ErrorDetail(
                    code="DEPENDENCY_CYCLE",
                    message="Payload dependency graph contains a directed cycle.",
                    scope="queue",
                    field_paths=("dependencies",),
                    affected_branches=("schedule",),
                )
            )
        self.storage.validate()
        for contact in self.contacts:
            if contact.station_key not in station_keys:
                raise DomainValidationError(
                    ErrorDetail(
                        code="UNKNOWN_CONTACT_STATION",
                        message="Every synthetic contact must reference a declared station.",
                        scope="contact",
                        field_paths=("contacts.station_key",),
                        affected_branches=("contact",),
                    )
                )
        if self.contact_source is not ContactSource.SYNTHETIC_INJECTED:
            raise DomainValidationError(
                ErrorDetail(
                    code="UNSUPPORTED_CONTACT_SOURCE",
                    message="P0 has no released orbit provider; ORBIT_DERIVED contacts stay "
                    "blocked until PB-GOLDEN-ORB-01 evidence exists.",
                    scope="scenario",
                    field_paths=("contact_source",),
                    affected_branches=("contact", "capacity", "schedule"),
                )
            )
        if self.synthetic_delivery_events:
            if self.storage.release_trigger is not ReleaseTrigger.ACKED:
                raise DomainValidationError(
                    ErrorDetail(
                        code="DELIVERY_EVENT_WITHOUT_ACK_TRIGGER",
                        message="Synthetic delivery events require release_trigger=ACKED.",
                        scope="storage",
                        field_paths=("synthetic_delivery_events", "storage.release_trigger"),
                        affected_branches=("storage",),
                    )
                )
            seen: set[str] = set()
            for event in self.synthetic_delivery_events:
                if event.payload_key not in payload_keys or event.payload_key in seen:
                    raise DomainValidationError(
                        ErrorDetail(
                            code="INVALID_DELIVERY_EVENT",
                            message="Each synthetic delivery event must reference a distinct "
                            "declared payload.",
                            scope="storage",
                            field_paths=("synthetic_delivery_events",),
                            affected_branches=("storage",),
                        )
                    )
                seen.add(event.payload_key)
        elif self.storage.release_trigger is ReleaseTrigger.ACKED:
            raise DomainValidationError(
                ErrorDetail(
                    code="ACK_TRIGGER_WITHOUT_DELIVERY_EVENT",
                    message="release_trigger=ACKED requires at least one synthetic test event; "
                    "P0 never ingests a real acknowledgement.",
                    scope="storage",
                    field_paths=("storage.release_trigger",),
                    affected_branches=("storage",),
                )
            )
        bundles: dict[str, set[BundleMemberRole]] = {}
        for payload in self.payloads:
            if payload.bundle_key is not None and payload.bundle_member_role is not None:
                bundles.setdefault(payload.bundle_key, set()).add(payload.bundle_member_role)
        for bundle_key, roles in sorted(bundles.items()):
            if roles == {BundleMemberRole.OPTIONAL}:
                raise DomainValidationError(
                    ErrorDetail(
                        code="BUNDLE_WITHOUT_REQUIRED_MEMBER",
                        message=f"Bundle {bundle_key} needs at least one required member.",
                        scope="queue",
                        field_paths=("payloads.bundle_member_role",),
                        affected_branches=("schedule",),
                    )
                )
