"""Event-ordered queue and storage reducer.

One pass produces the payload allocations, the queue/storage event timeline and the storage
occupancy ledger, so that same-timestamp ordering is decided in exactly one place. The order is
``CLOSE_RELEASE_ADMIT_ALLOCATE_V1`` from the accepted v1.3 baseline:

    1. close the allocations that end at t
    2. commit modeled TX progress at TX_END
    3. ingest test/observed delivery events
    4. evaluate release eligibility
    5. reclaim eligible whole objects and commit occupancy
    6. generation / ready events
    7. validation and admission pre-check
    9. commit admission or whole-object rejection
   10. evaluate ready/dependency/deadline/expiry eligibility
   12. open the allocations that start at t

Every byte here is a *modeled* logical byte. Nothing in this module observes a real
acknowledgement, a real ground reception, or a real recorder.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .enums import (
    BundleMemberRole,
    BundleStatus,
    CapacityProvider,
    DeliveryAssumption,
    DeliveryConfirmationState,
    EventDomain,
    EventKind,
    ReasonCode,
    ReleaseTrigger,
    ReserveEnforcement,
    SegmentationKind,
    ServiceClass,
    StorageMode,
)
from .models import (
    CapacityProfile,
    Payload,
    PayloadDependency,
    StorageConfig,
    SyntheticDeliveryEvent,
)
from .queue import allocation_end, queue_order_key, rate_bytes_remaining
from .scheduler import Candidate
from .time import TimeInterval, UtcInstant

EVENT_ORDER_REVISION = "CLOSE_RELEASE_ADMIT_ALLOCATE_V1"


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    event_at: UtcInstant
    event_order: int
    event_domain: EventDomain
    event_kind: EventKind
    reason_code: ReasonCode
    payload_key: str | None = None
    allocation_key: str | None = None
    delta_logical_bytes: int | None = None
    remaining_logical_bytes: int | None = None
    delta_storage_bytes: int | None = None
    occupancy_bytes: int | None = None
    reserve_breach_bytes: int | None = None
    rejected_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class PayloadAllocation:
    stable_key: str
    payload_key: str
    session_key: str
    station_key: str
    allocation_ordinal: int
    logical_offset_start: int
    start: UtcInstant
    end: UtcInstant
    allocated_bytes: int
    remaining_bytes_after: int
    modeled_tx_complete_at: UtcInstant | None
    reason_code: ReasonCode


@dataclass(frozen=True, slots=True)
class PayloadProgress:
    payload_key: str
    logical_size_bytes: int
    allocated_bytes: int
    remaining_bytes: int
    modeled_tx_complete_at: UtcInstant | None
    partial_transfer_end_at: UtcInstant | None
    reason_codes: tuple[ReasonCode, ...]


@dataclass(frozen=True, slots=True)
class StorageAdmission:
    payload_key: str
    admitted: bool
    occupancy_after_bytes: int
    reason_code: ReasonCode | None


@dataclass(frozen=True, slots=True)
class OccupancySample:
    at: UtcInstant
    occupancy_bytes: int


@dataclass(frozen=True, slots=True)
class BundleResult:
    bundle_key: str
    modeled_required_members_tx_complete_at: UtcInstant | None
    assumed_actionable_at: UtcInstant | None
    delivery_confirmation_state: DeliveryConfirmationState
    actionable_status: BundleStatus
    complete_status: BundleStatus
    reason_codes: tuple[ReasonCode, ...]


@dataclass(frozen=True, slots=True)
class StorageLedger:
    applicable: bool
    physical_capacity_bytes: int | None
    reserve_bytes: int | None
    usable_limit_bytes: int | None
    final_occupancy_bytes: int | None
    peak_occupancy_bytes: int | None
    hard_overflow_bytes: int | None
    reserve_breach_bytes: int | None
    peak_reserve_breach_bytes: int | None
    released_bytes: int | None
    rejected_object_count: int | None
    rejected_bytes: int | None
    admissions: tuple[StorageAdmission, ...]
    occupancy_timeline: tuple[OccupancySample, ...]


@dataclass(frozen=True, slots=True)
class LedgerResult:
    allocations: tuple[PayloadAllocation, ...]
    progress: tuple[PayloadProgress, ...]
    events: tuple[LedgerEvent, ...]
    storage: StorageLedger
    bundles: tuple[BundleResult, ...]
    stranded_capacity_bytes: int
    admitted_payload_keys: frozenset[str]


@dataclass(slots=True)
class _State:
    remaining: dict[str, int] = field(default_factory=dict)
    completion: dict[str, UtcInstant | None] = field(default_factory=dict)
    partial_end: dict[str, UtcInstant | None] = field(default_factory=dict)
    reasons: dict[str, list[ReasonCode]] = field(default_factory=dict)
    occupancy: int = 0
    peak_occupancy: int = 0
    peak_breach: int = 0
    released_bytes: int = 0
    rejected_bytes: int = 0
    admitted: set[str] = field(default_factory=set)
    released: set[str] = field(default_factory=set)
    acknowledged: dict[str, UtcInstant] = field(default_factory=dict)
    admissions: list[StorageAdmission] = field(default_factory=list)
    occupancy_timeline: list[OccupancySample] = field(default_factory=list)
    events: list[LedgerEvent] = field(default_factory=list)
    allocations: list[PayloadAllocation] = field(default_factory=list)
    order_at: dict[int, int] = field(default_factory=dict)


class _Reducer:
    def __init__(
        self,
        sessions: tuple[Candidate, ...],
        profiles_by_station: dict[str, CapacityProfile],
        payloads: tuple[Payload, ...],
        dependencies: tuple[PayloadDependency, ...],
        storage: StorageConfig,
        analysis_window: TimeInterval,
        delivery_events: tuple[SyntheticDeliveryEvent, ...],
    ) -> None:
        self._sessions = tuple(
            sorted(sessions, key=lambda item: (item.interval.start, item.stable_key))
        )
        self._profiles = profiles_by_station
        self._payloads = tuple(sorted(payloads, key=lambda item: item.stable_key))
        self._ordered = tuple(sorted(payloads, key=queue_order_key))
        self._by_key = {payload.stable_key: payload for payload in payloads}
        self._storage = storage
        self._window = analysis_window
        self._enabled = storage.mode is StorageMode.ENABLED
        self._predecessors: dict[str, set[str]] = {
            payload.stable_key: set() for payload in payloads
        }
        for dependency in dependencies:
            self._predecessors[dependency.successor_key].add(dependency.predecessor_key)
        self._pending_generation = list(
            sorted(payloads, key=lambda item: (item.ready_at, item.queue_sequence, item.stable_key))
        )
        self._pending_delivery = list(
            sorted(delivery_events, key=lambda item: (item.acknowledged_at, item.payload_key))
        )
        self._state = _State(
            remaining={payload.stable_key: payload.logical_size_bytes for payload in payloads},
            completion={payload.stable_key: None for payload in payloads},
            partial_end={payload.stable_key: None for payload in payloads},
            reasons={payload.stable_key: [] for payload in payloads},
            occupancy=storage.initial_occupancy_bytes if self._enabled else 0,
        )
        self._state.peak_occupancy = self._state.occupancy
        if self._enabled:
            self._state.peak_breach = max(0, self._state.occupancy - storage.usable_limit_bytes)
            self._state.occupancy_timeline.append(
                OccupancySample(analysis_window.start, self._state.occupancy)
            )

    # -- event helpers -------------------------------------------------------

    def _next_order(self, at: UtcInstant) -> int:
        order = self._state.order_at.get(at.microseconds, 0)
        self._state.order_at[at.microseconds] = order + 1
        return order

    def _queue_event(
        self,
        at: UtcInstant,
        kind: EventKind,
        reason: ReasonCode,
        payload_key: str,
        allocation_key: str | None = None,
        delta_logical_bytes: int | None = None,
        remaining_logical_bytes: int | None = None,
    ) -> None:
        self._state.events.append(
            LedgerEvent(
                event_at=at,
                event_order=self._next_order(at),
                event_domain=EventDomain.QUEUE,
                event_kind=kind,
                reason_code=reason,
                payload_key=payload_key,
                allocation_key=allocation_key,
                delta_logical_bytes=delta_logical_bytes,
                remaining_logical_bytes=remaining_logical_bytes,
            )
        )

    def _storage_event(
        self,
        at: UtcInstant,
        kind: EventKind,
        reason: ReasonCode,
        payload_key: str,
        delta_storage_bytes: int | None = None,
        rejected_bytes: int | None = None,
    ) -> None:
        breach = max(0, self._state.occupancy - self._storage.usable_limit_bytes)
        self._state.peak_breach = max(self._state.peak_breach, breach)
        self._state.events.append(
            LedgerEvent(
                event_at=at,
                event_order=self._next_order(at),
                event_domain=EventDomain.STORAGE,
                event_kind=kind,
                reason_code=reason,
                payload_key=payload_key,
                delta_storage_bytes=delta_storage_bytes,
                occupancy_bytes=self._state.occupancy,
                reserve_breach_bytes=breach,
                rejected_bytes=rejected_bytes,
            )
        )
        self._state.occupancy_timeline.append(OccupancySample(at, self._state.occupancy))

    # -- canonical stages ----------------------------------------------------

    def _ingest_delivery(self, at: UtcInstant) -> None:
        while self._pending_delivery and self._pending_delivery[0].acknowledged_at == at:
            event = self._pending_delivery.pop(0)
            self._state.acknowledged[event.payload_key] = at
            self._queue_event(
                at,
                EventKind.TEST_DELIVERY_INGESTED,
                ReasonCode.RELEASED_ON_ACK,
                event.payload_key,
                remaining_logical_bytes=self._state.remaining[event.payload_key],
            )

    def _release(self, at: UtcInstant) -> None:
        if not self._enabled or self._storage.release_trigger is ReleaseTrigger.NEVER:
            return
        trigger = self._storage.release_trigger
        for payload in self._payloads:
            key = payload.stable_key
            if key in self._state.released or key not in self._state.admitted:
                continue
            if trigger is ReleaseTrigger.TX_END:
                completion = self._state.completion[key]
                eligible = completion is not None and completion == at
                reason = ReasonCode.RELEASED_TX_END_PROXY
            else:
                acknowledged = self._state.acknowledged.get(key)
                eligible = acknowledged is not None and acknowledged == at
                reason = ReasonCode.RELEASED_ON_ACK
            if not eligible:
                continue
            if self._state.remaining[key] != 0:
                # Object reclaim never returns storage for a partially transferred object.
                self._state.reasons[key].append(ReasonCode.RELEASE_HELD_INCOMPLETE_OBJECT)
                self._storage_event(
                    at,
                    EventKind.RELEASE_HELD,
                    ReasonCode.RELEASE_HELD_INCOMPLETE_OBJECT,
                    key,
                    delta_storage_bytes=0,
                )
                continue
            self._state.released.add(key)
            self._state.occupancy -= payload.storage_size_bytes
            self._state.released_bytes += payload.storage_size_bytes
            self._storage_event(
                at,
                EventKind.OBJECT_RELEASED,
                reason,
                key,
                delta_storage_bytes=-payload.storage_size_bytes,
            )

    def _generate_and_admit(self, at: UtcInstant) -> None:
        while self._pending_generation and self._pending_generation[0].ready_at == at:
            payload = self._pending_generation.pop(0)
            key = payload.stable_key
            self._queue_event(
                at,
                EventKind.OBJECT_GENERATED,
                ReasonCode.OBJECT_GENERATED_AT_READY,
                key,
                remaining_logical_bytes=self._state.remaining[key],
            )
            if not self._enabled:
                self._state.admitted.add(key)
                continue
            projected = self._state.occupancy + payload.storage_size_bytes
            assert self._storage.physical_capacity_bytes is not None
            if projected > self._storage.physical_capacity_bytes:
                reason = ReasonCode.ADMISSION_REJECTED_PHYSICAL_LIMIT
            elif (
                self._storage.reserve_enforcement is ReserveEnforcement.HARD
                and projected > self._storage.usable_limit_bytes
            ):
                reason = ReasonCode.ADMISSION_REJECTED_HARD_RESERVE
            else:
                reason = None
            if reason is not None:
                self._state.rejected_bytes += payload.storage_size_bytes
                self._state.reasons[key].append(reason)
                self._state.admissions.append(
                    StorageAdmission(key, False, self._state.occupancy, reason)
                )
                self._storage_event(
                    at,
                    EventKind.OBJECT_REJECTED,
                    reason,
                    key,
                    delta_storage_bytes=0,
                    rejected_bytes=payload.storage_size_bytes,
                )
                continue
            self._state.occupancy = projected
            self._state.peak_occupancy = max(self._state.peak_occupancy, projected)
            self._state.admitted.add(key)
            breached = (
                self._storage.reserve_enforcement is ReserveEnforcement.SOFT
                and projected > self._storage.usable_limit_bytes
            )
            admit_reason = ReasonCode.RESERVE_BREACH_SOFT if breached else None
            self._state.admissions.append(StorageAdmission(key, True, projected, admit_reason))
            if admit_reason is not None:
                self._state.reasons[key].append(admit_reason)
            self._storage_event(
                at,
                EventKind.OBJECT_ADMITTED,
                admit_reason or ReasonCode.OBJECT_GENERATED_AT_READY,
                key,
                delta_storage_bytes=payload.storage_size_bytes,
            )

    def _advance_to(self, at: UtcInstant) -> None:
        """Apply every pending event with `event_at <= at` in canonical stage order."""
        while True:
            candidates = [
                item.acknowledged_at
                for item in self._pending_delivery[:1]
                if item.acknowledged_at <= at
            ] + [item.ready_at for item in self._pending_generation[:1] if item.ready_at <= at]
            if not candidates:
                return
            instant = min(candidates)
            self._ingest_delivery(instant)
            self._release(instant)
            self._generate_and_admit(instant)

    # -- allocation ----------------------------------------------------------

    def _eligible(self, payload: Payload, cursor: UtcInstant) -> bool:
        key = payload.stable_key
        if self._state.remaining[key] <= 0 or key not in self._state.admitted:
            return False
        if payload.ready_at > cursor:
            return False
        if payload.expiry_at is not None and cursor >= payload.expiry_at:
            return False
        for predecessor in self._predecessors[key]:
            completion = self._state.completion[predecessor]
            if completion is None or completion > cursor:
                return False
        return True

    def _choose(self, cursor: UtcInstant, available: int) -> tuple[Payload, int, ReasonCode] | None:
        for payload in self._ordered:
            if not self._eligible(payload, cursor):
                continue
            remaining = self._state.remaining[payload.stable_key]
            select_reason = (
                ReasonCode.PAYLOAD_SELECTED_MANDATORY
                if payload.service_class is ServiceClass.MANDATORY
                else ReasonCode.PAYLOAD_SELECTED_DEADLINE_SEVERITY
            )
            if payload.segmentation is SegmentationKind.ATOMIC_OBJECT:
                # transfer_start_policy = ONLY_IF_COMPLETABLE: never start what cannot finish.
                if remaining <= available:
                    return payload, remaining, select_reason
                self._note(payload.stable_key, ReasonCode.NOT_STARTED_ATOMIC_NOT_COMPLETABLE)
                continue
            assert payload.chunk_size_bytes is not None
            grant = min(remaining, available)
            if grant < remaining:
                grant -= grant % payload.chunk_size_bytes
            if grant > 0:
                return payload, grant, select_reason
            self._note(payload.stable_key, ReasonCode.DEFERRED_NO_REMAINING_CAPACITY)
        return None

    def _note(self, payload_key: str, reason: ReasonCode) -> None:
        if reason not in self._state.reasons[payload_key]:
            self._state.reasons[payload_key].append(reason)

    def _run_session(self, session: Candidate) -> int:
        profile = self._profiles[session.station_key]
        available = session.capacity_bytes
        cursor = session.interval.start
        self._advance_to(cursor)
        while available > 0 and cursor < session.interval.end:
            available = min(available, rate_bytes_remaining(session, profile, cursor))
            if available <= 0:
                break
            chosen = self._choose(cursor, available)
            if chosen is None:
                if profile.provider is CapacityProvider.FIXED_CAPACITY_PER_CONTACT:
                    # No in-pass rate evidence: eligibility is decided once, at session start.
                    break
                future = [
                    payload.ready_at
                    for payload in self._ordered
                    if self._state.remaining[payload.stable_key] > 0
                    and cursor < payload.ready_at < session.interval.end
                ]
                if not future:
                    break
                cursor = min(future)
                self._advance_to(cursor)
                continue
            payload, granted, select_reason = chosen
            key = payload.stable_key
            offset = payload.logical_size_bytes - self._state.remaining[key]
            end = allocation_end(session, profile, cursor, granted)
            allocation_key = f"allocation/{session.stable_key}/{len(self._state.allocations):04d}"
            self._queue_event(
                cursor,
                EventKind.ALLOCATION_OPEN,
                select_reason,
                key,
                allocation_key=allocation_key,
                delta_logical_bytes=0,
                remaining_logical_bytes=self._state.remaining[key],
            )
            self._state.remaining[key] -= granted
            available -= granted
            remaining_after = self._state.remaining[key]
            complete_at = end if remaining_after == 0 else None
            if complete_at is not None:
                self._state.completion[key] = complete_at
                self._state.partial_end[key] = None
            else:
                self._state.partial_end[key] = end
                self._note(
                    key,
                    ReasonCode.SPLIT_FIXED_CHUNK_BOUNDARY
                    if payload.segmentation is SegmentationKind.FIXED_CHUNK
                    else ReasonCode.SPLIT_SESSION_CAPACITY,
                )
                self._note(key, ReasonCode.RESUME_NEXT_SESSION)
            self._state.allocations.append(
                PayloadAllocation(
                    stable_key=allocation_key,
                    payload_key=key,
                    session_key=session.stable_key,
                    station_key=session.station_key,
                    allocation_ordinal=sum(
                        1
                        for item in self._state.allocations
                        if item.session_key == session.stable_key
                    ),
                    logical_offset_start=offset,
                    start=cursor,
                    end=end,
                    allocated_bytes=granted,
                    remaining_bytes_after=remaining_after,
                    modeled_tx_complete_at=complete_at,
                    reason_code=select_reason,
                )
            )
            self._queue_event(
                end,
                EventKind.ALLOCATION_CLOSE,
                select_reason,
                key,
                allocation_key=allocation_key,
                delta_logical_bytes=granted,
                remaining_logical_bytes=remaining_after,
            )
            self._queue_event(
                end,
                EventKind.MODELED_TX_PROGRESS_AT_TX_END,
                select_reason,
                key,
                allocation_key=allocation_key,
                delta_logical_bytes=granted,
                remaining_logical_bytes=remaining_after,
            )
            self._release(end)
            self._advance_to(end)
            cursor = end
        return available

    # -- finalisation --------------------------------------------------------

    def _bundles(self) -> tuple[BundleResult, ...]:
        groups: dict[str, list[Payload]] = {}
        for payload in self._payloads:
            if payload.bundle_key is not None:
                groups.setdefault(payload.bundle_key, []).append(payload)
        assumed = (
            self._enabled
            and self._storage.delivery_assumption is DeliveryAssumption.TX_END_EQUALS_DELIVERED
        )
        results: list[BundleResult] = []
        for bundle_key, members in sorted(groups.items()):
            required = [
                member
                for member in members
                if member.bundle_member_role
                in {BundleMemberRole.REQUIRED_ACTIONABLE, BundleMemberRole.REQUIRED_COMPLETE}
            ]
            optional = [
                member
                for member in members
                if member.bundle_member_role is BundleMemberRole.OPTIONAL
            ]
            required_times = [self._state.completion[member.stable_key] for member in required]
            all_times = [self._state.completion[member.stable_key] for member in members]
            reasons: list[ReasonCode] = []
            if required_times and all(item is not None for item in required_times):
                required_complete_at = max(item for item in required_times if item is not None)
                actionable = BundleStatus.ACHIEVED
                reasons.append(ReasonCode.BUNDLE_ACTIONABLE_REQUIRED_MEMBERS_COMPLETE)
            else:
                required_complete_at = None
                actionable = BundleStatus.UNACHIEVABLE
                reasons.append(ReasonCode.BUNDLE_UNACHIEVABLE_REQUIRED_MISSING)
            if all(item is not None for item in all_times):
                complete = BundleStatus.ACHIEVED
            elif actionable is BundleStatus.ACHIEVED and optional:
                complete = BundleStatus.DEGRADED
                reasons.append(ReasonCode.BUNDLE_DEGRADED_OPTIONAL_MISSING)
            else:
                complete = BundleStatus.UNACHIEVABLE
            results.append(
                BundleResult(
                    bundle_key=bundle_key,
                    modeled_required_members_tx_complete_at=required_complete_at,
                    assumed_actionable_at=required_complete_at if assumed else None,
                    delivery_confirmation_state=(
                        DeliveryConfirmationState.ASSUMED
                        if assumed and required_complete_at is not None
                        else DeliveryConfirmationState.NOT_OBSERVED
                    ),
                    actionable_status=actionable,
                    complete_status=complete,
                    reason_codes=tuple(reasons),
                )
            )
        return tuple(results)

    def run(self) -> LedgerResult:
        stranded = 0
        for session in self._sessions:
            stranded += self._run_session(session)
        self._advance_to(self._window.end)
        state = self._state
        for payload in self._payloads:
            key = payload.stable_key
            if (
                state.remaining[key] > 0
                and key in state.admitted
                and payload.expiry_at is not None
                and payload.expiry_at <= self._window.end
            ):
                self._note(
                    key,
                    ReasonCode.EXPIRED_AFTER_PARTIAL
                    if state.partial_end[key] is not None
                    else ReasonCode.EXPIRED_BEFORE_START,
                )
            if payload.deadline_at is not None:
                completion = state.completion[key]
                if completion is not None and completion > payload.deadline_at:
                    self._note(key, ReasonCode.DEADLINE_MISSED_CONTINUE)
            if (
                self._enabled
                and self._storage.release_trigger is not ReleaseTrigger.NEVER
                and key in state.admitted
                and key not in state.released
                and state.remaining[key] > 0
            ):
                self._note(key, ReasonCode.RELEASE_HELD_INCOMPLETE_OBJECT)
        progress = tuple(
            PayloadProgress(
                payload_key=payload.stable_key,
                logical_size_bytes=payload.logical_size_bytes,
                allocated_bytes=payload.logical_size_bytes - state.remaining[payload.stable_key],
                remaining_bytes=state.remaining[payload.stable_key],
                modeled_tx_complete_at=state.completion[payload.stable_key],
                partial_transfer_end_at=state.partial_end[payload.stable_key],
                reason_codes=tuple(state.reasons[payload.stable_key]),
            )
            for payload in self._payloads
        )
        if self._enabled:
            assert self._storage.physical_capacity_bytes is not None
            storage = StorageLedger(
                applicable=True,
                physical_capacity_bytes=self._storage.physical_capacity_bytes,
                reserve_bytes=self._storage.reserve_bytes,
                usable_limit_bytes=self._storage.usable_limit_bytes,
                final_occupancy_bytes=state.occupancy,
                peak_occupancy_bytes=state.peak_occupancy,
                hard_overflow_bytes=max(
                    0, state.peak_occupancy - self._storage.physical_capacity_bytes
                ),
                reserve_breach_bytes=max(0, state.occupancy - self._storage.usable_limit_bytes),
                peak_reserve_breach_bytes=state.peak_breach,
                released_bytes=state.released_bytes,
                rejected_object_count=sum(1 for item in state.admissions if not item.admitted),
                rejected_bytes=state.rejected_bytes,
                admissions=tuple(state.admissions),
                occupancy_timeline=tuple(state.occupancy_timeline),
            )
        else:
            storage = StorageLedger(
                applicable=False,
                physical_capacity_bytes=None,
                reserve_bytes=None,
                usable_limit_bytes=None,
                final_occupancy_bytes=None,
                peak_occupancy_bytes=None,
                hard_overflow_bytes=None,
                reserve_breach_bytes=None,
                peak_reserve_breach_bytes=None,
                released_bytes=None,
                rejected_object_count=None,
                rejected_bytes=None,
                admissions=(),
                occupancy_timeline=(),
            )
        return LedgerResult(
            allocations=tuple(state.allocations),
            progress=progress,
            events=tuple(state.events),
            storage=storage,
            bundles=self._bundles(),
            stranded_capacity_bytes=stranded,
            admitted_payload_keys=frozenset(state.admitted),
        )


def run_ledger(
    sessions: tuple[Candidate, ...],
    profiles_by_station: dict[str, CapacityProfile],
    payloads: tuple[Payload, ...],
    dependencies: tuple[PayloadDependency, ...],
    storage: StorageConfig,
    analysis_window: TimeInterval,
    delivery_events: tuple[SyntheticDeliveryEvent, ...] = (),
) -> LedgerResult:
    return _Reducer(
        sessions,
        profiles_by_station,
        payloads,
        dependencies,
        storage,
        analysis_window,
        delivery_events,
    ).run()
