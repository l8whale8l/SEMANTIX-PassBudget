from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import pairwise
from typing import cast

from . import limits
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
    ExecutionStrategy,
    OrbitKind,
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


#: WGS-84 geodetic ranges, expressed in the exact integer micro-units the canonical hash accepts.
#: Latitude is south-negative, longitude is east-positive (contract §6), height is above the
#: WGS-84 ellipsoid, and the elevation mask is a non-negative angle below 90 degrees.
MIN_LATITUDE_UDEG = -90_000_000
MAX_LATITUDE_UDEG = 90_000_000
MIN_LONGITUDE_UDEG = -180_000_000
MAX_LONGITUDE_UDEG = 180_000_000
MIN_ELLIPSOIDAL_HEIGHT_MM = -1_000_000
MAX_ELLIPSOIDAL_HEIGHT_MM = 10_000_000_000
MAX_ELEVATION_MASK_UDEG = 90_000_000


@dataclass(frozen=True, slots=True)
class GeodeticSite:
    """A ground station's WGS-84 position and its constant elevation mask.

    Present only for ``ORBIT_DERIVED`` scenarios; forbidden for ``SYNTHETIC_INJECTED`` ones, where
    a contact carries no station geometry (ADR-0002). Every value is an exact integer in a
    micro-unit so it can enter the canonical input hash without a binary float. The orbit adapter
    converts these to floating-point degrees and metres at its own boundary, per ADR-0001.
    """

    latitude_udeg: int
    longitude_east_udeg: int
    ellipsoidal_height_mm: int
    minimum_elevation_udeg: int

    def validate(self, station_key: str) -> None:
        if not MIN_LATITUDE_UDEG <= self.latitude_udeg <= MAX_LATITUDE_UDEG:
            self._invalid(station_key, "latitude is bounded to [-90, +90] degrees.")
        if not MIN_LONGITUDE_UDEG <= self.longitude_east_udeg <= MAX_LONGITUDE_UDEG:
            self._invalid(station_key, "east longitude is bounded to [-180, +180] degrees.")
        if not MIN_ELLIPSOIDAL_HEIGHT_MM <= self.ellipsoidal_height_mm <= MAX_ELLIPSOIDAL_HEIGHT_MM:
            self._invalid(station_key, "ellipsoidal height is out of the accepted range.")
        if not 0 <= self.minimum_elevation_udeg < MAX_ELEVATION_MASK_UDEG:
            self._invalid(station_key, "minimum elevation is bounded to [0, 90) degrees.")

    @staticmethod
    def _invalid(station_key: str, message: str) -> None:
        raise DomainValidationError(
            ErrorDetail(
                code="INVALID_STATION_SITE",
                message=message,
                scope="scenario",
                field_paths=(f"stations.{station_key}.site",),
                affected_branches=("contact", "capacity", "schedule"),
            )
        )


@dataclass(frozen=True, slots=True)
class Station:
    stable_key: str
    preference_rank: int
    capacity: CapacityProfile
    #: WGS-84 position and elevation mask. Required for ORBIT_DERIVED, forbidden otherwise.
    site: GeodeticSite | None = None


@dataclass(frozen=True, slots=True)
class TleElements:
    """A two-line element set supplied as request data, propagated with SGP4.

    The lines are stored verbatim as strings (never re-parsed into floats), so they are exact
    canonical input. A user-supplied TLE describes whatever object the user chose; it is never a
    KMU-ET02 orbit and no result derived from it is a KMU performance figure.
    """

    line_1: str
    line_2: str

    def validate(self) -> None:
        for ordinal, line in ((1, self.line_1), (2, self.line_2)):
            if len(line) != 69 or not line.startswith(f"{ordinal} "):
                raise DomainValidationError(
                    ErrorDetail(
                        code="INVALID_TLE",
                        message="Each TLE line must be 69 chars and begin with its line number.",
                        scope="scenario",
                        field_paths=(f"orbit.tle.line_{ordinal}",),
                        affected_branches=("contact",),
                    )
                )


@dataclass(frozen=True, slots=True)
class TwoBodyElements:
    """Literal Keplerian elements propagated under point-mass gravity (``TWO_BODY_V1``).

    Every field is an exact integer micro-unit so the assumption is canonical input, matching the
    frozen ``EVD-ORB-02`` reference orbit. This is a synthetic reference orbit, not a spacecraft.
    """

    epoch: UtcInstant
    semi_major_axis_mm: int
    eccentricity_ppb: int
    inclination_udeg: int
    raan_udeg: int
    argument_of_perigee_udeg: int
    true_anomaly_udeg: int
    mu_m3_per_s2: int

    def validate(self) -> None:
        if self.semi_major_axis_mm <= 0 or self.mu_m3_per_s2 <= 0:
            self._invalid("Semi-major axis and gravitational parameter must be positive.")
        # P0 supports the circular reference profile only; a non-zero eccentricity would need the
        # eccentric-anomaly seeding that circular_state_from_elements does not carry.
        if self.eccentricity_ppb != 0:
            self._invalid("TWO_BODY_V1 supports only the circular profile (eccentricity = 0).")
        if not 0 <= self.inclination_udeg <= 180_000_000:
            self._invalid("Inclination is bounded to [0, 180] degrees.")
        for name, value in (
            ("raan", self.raan_udeg),
            ("argument_of_perigee", self.argument_of_perigee_udeg),
            ("true_anomaly", self.true_anomaly_udeg),
        ):
            if not 0 <= value < 360_000_000:
                self._invalid(f"{name} is bounded to [0, 360) degrees.")

    @staticmethod
    def _invalid(message: str) -> None:
        raise DomainValidationError(
            ErrorDetail(
                code="INVALID_TWO_BODY_ELEMENTS",
                message=message,
                scope="scenario",
                field_paths=("orbit.two_body",),
                affected_branches=("contact",),
            )
        )


@dataclass(frozen=True, slots=True)
class OrbitSpec:
    """The orbit assumption an ``ORBIT_DERIVED`` scenario propagates to generate contact windows.

    Exactly one of ``tle`` / ``two_body`` is present, matching ``kind``. The engine revisions are
    not carried here: they are stated by the provider that actually computes the passes, so a user
    cannot mislabel which algorithm produced a result.
    """

    kind: OrbitKind
    tle: TleElements | None = None
    two_body: TwoBodyElements | None = None

    def validate(self) -> None:
        if self.kind is OrbitKind.GP_TLE:
            if self.tle is None or self.two_body is not None:
                self._invalid("GP_TLE requires TLE lines and forbids two-body elements.")
            assert self.tle is not None
            self.tle.validate()
        else:
            if self.two_body is None or self.tle is not None:
                self._invalid("TWO_BODY_V1 requires two-body elements and forbids TLE lines.")
            assert self.two_body is not None
            self.two_body.validate()

    @staticmethod
    def _invalid(message: str) -> None:
        raise DomainValidationError(
            ErrorDetail(
                code="INVALID_ORBIT_SPEC",
                message=message,
                scope="scenario",
                field_paths=("orbit",),
                affected_branches=("contact", "capacity", "schedule"),
            )
        )


@dataclass(frozen=True, slots=True)
class SyntheticContact:
    """One contact interval fed into the capacity pipeline.

    The name is historical: this is the single contact type for both sources. For
    ``SYNTHETIC_INJECTED`` the geometry fields stay ``None`` (a synthetic contact has no
    propagator and no elevation). For ``ORBIT_DERIVED`` the provider fills them from the pass it
    computed, and they surface in the geometric-access result and its persisted row.
    """

    stable_key: str
    station_key: str
    true_interval: TimeInterval
    maximum_elevation_udeg: int | None = None
    maximum_elevation_time: UtcInstant | None = None
    clipped_start: bool = False
    clipped_end: bool = False


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
    execution_strategy: ExecutionStrategy = ExecutionStrategy.EXACT_GLOBAL
    #: The orbit assumption for ORBIT_DERIVED scenarios. Required then, forbidden otherwise.
    orbit: OrbitSpec | None = None

    def _enforce_input_limits(self) -> None:
        """Refuse an oversized scenario before any branch runs.

        This sits at the top of `validate()` rather than in a DTO because every entry point --
        HTTP, CLI and a direct domain caller -- reaches `validate()`, and only some of them reach
        a DTO. An oversized input is refused whole: it is not truncated, and it is not the same
        thing as a branch-local calculation failure, which leaves the run PARTIAL with the
        successful branches readable. See `domain/limits.py`.
        """
        limits.enforce(
            limit_name="analysis window",
            actual=self.analysis_window.end.microseconds - self.analysis_window.start.microseconds,
            maximum=limits.MAX_ANALYSIS_WINDOW_US,
            unit="microseconds",
            scope="scenario",
            field_path="analysis_window",
            affected_branches=("contact", "capacity", "schedule", "queue", "storage"),
        )
        limits.enforce(
            limit_name="station count",
            actual=len(self.stations),
            maximum=limits.MAX_STATIONS,
            unit="stations",
            scope="scenario",
            field_path="stations",
            affected_branches=("contact", "capacity", "schedule"),
        )
        limits.enforce(
            limit_name="contact count",
            actual=len(self.contacts),
            maximum=limits.MAX_CONTACTS,
            unit="contacts",
            scope="contact",
            field_path="contacts",
            affected_branches=("contact", "capacity", "schedule"),
        )
        limits.enforce(
            limit_name="payload count",
            actual=len(self.payloads),
            maximum=limits.MAX_PAYLOADS,
            unit="payloads",
            scope="queue",
            field_path="payloads",
            affected_branches=("schedule", "queue", "storage"),
        )
        limits.enforce(
            limit_name="payload dependency count",
            actual=len(self.dependencies),
            maximum=limits.MAX_DEPENDENCIES,
            unit="dependencies",
            scope="queue",
            field_path="dependencies",
            affected_branches=("schedule", "queue"),
        )
        limits.enforce(
            limit_name="synthetic delivery event count",
            actual=len(self.synthetic_delivery_events),
            maximum=limits.MAX_SYNTHETIC_DELIVERY_EVENTS,
            unit="events",
            scope="storage",
            field_path="synthetic_delivery_events",
            affected_branches=("storage",),
        )
        for station in self.stations:
            limits.enforce(
                limit_name="rate segment count for one station",
                actual=len(station.capacity.rate_segments),
                maximum=limits.MAX_RATE_SEGMENTS_PER_STATION,
                unit="segments",
                scope="capacity",
                field_path="stations.capacity.rate_segments",
                affected_branches=("capacity",),
            )
            limits.enforce(
                limit_name="time reserve count for one station",
                actual=len(station.capacity.time_reserves),
                maximum=limits.MAX_TIME_RESERVES_PER_STATION,
                unit="reserves",
                scope="capacity",
                field_path="stations.capacity.time_reserves",
                affected_branches=("capacity",),
            )

    def _validate_contact_source(self) -> None:
        """Enforce the ADR-0002 provenance split at the domain boundary.

        ORBIT_DERIVED needs an orbit assumption and full station geometry, and the provider
        generates its contacts, so injecting a contact list is a conflict. SYNTHETIC_INJECTED is
        the mirror image: no orbit, no station geometry, no fabricated elevation. The database
        CHECK constraints (ADR-0002) enforce the same rule at the row level; keeping both in step
        is deliberate.
        """
        if self.contact_source is ContactSource.ORBIT_DERIVED:
            if self.orbit is None:
                self._source_error(
                    "MISSING_ORBIT_SPEC",
                    "ORBIT_DERIVED requires an orbit assumption to propagate.",
                    ("orbit",),
                )
            if self.contacts:
                self._source_error(
                    "ORBIT_DERIVED_CONTACTS_ARE_GENERATED",
                    "ORBIT_DERIVED generates its own contacts; an injected contact list is a "
                    "conflict. Provide the orbit and stations, not contacts.",
                    ("contacts",),
                )
            for station in self.stations:
                if station.site is None:
                    self._source_error(
                        "MISSING_STATION_SITE",
                        "ORBIT_DERIVED requires WGS-84 coordinates and an elevation mask for "
                        f"every station; {station.stable_key} has none.",
                        ("stations.site",),
                    )
                else:
                    station.site.validate(station.stable_key)
            assert self.orbit is not None
            self.orbit.validate()
        else:
            if self.orbit is not None:
                self._source_error(
                    "SYNTHETIC_FORBIDS_ORBIT_SPEC",
                    "SYNTHETIC_INJECTED contacts carry no orbit assumption.",
                    ("orbit",),
                )
            for station in self.stations:
                if station.site is not None:
                    self._source_error(
                        "SYNTHETIC_FORBIDS_STATION_SITE",
                        "SYNTHETIC_INJECTED contacts carry no station geometry; "
                        f"{station.stable_key} declares a site.",
                        ("stations.site",),
                    )

    @staticmethod
    def _source_error(code: str, message: str, field_paths: tuple[str, ...]) -> None:
        raise DomainValidationError(
            ErrorDetail(
                code=code,
                message=message,
                scope="scenario",
                field_paths=field_paths,
                affected_branches=("contact", "capacity", "schedule"),
            )
        )

    def validate(self) -> None:
        self._enforce_input_limits()
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
        if (
            self.analysis_mode is not AnalysisMode.QUEUE_AWARE
            and self.execution_strategy is not ExecutionStrategy.EXACT_GLOBAL
        ):
            raise DomainValidationError(
                ErrorDetail(
                    code="EXECUTION_STRATEGY_NOT_APPLICABLE",
                    message=(
                        "Only QUEUE_AWARE resolves overlap by search. NETWORK_ONLY is solved "
                        "exactly by the maximum-capacity dynamic program, so asking for a "
                        "bounded approximation there would label an exact result approximate."
                    ),
                    scope="scenario",
                    field_paths=("analysis_mode", "execution_strategy"),
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
        self._validate_contact_source()
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
