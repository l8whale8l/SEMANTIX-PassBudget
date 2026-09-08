"""Decompose a validated scenario snapshot into the typed catalog rows the schema defines.

The same decomposition feeds preset seeding and PostgreSQL persistence, so the relational shape
and the in-memory shape can never drift apart. Every identifier produced here is a deterministic
stable key derived from the snapshot, never a random value and never a host-specific string.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from semantix_passbudget.domain.enums import (
    AnalysisMode,
    CapacityProvider,
    ProfileKind,
    SegmentationKind,
)
from semantix_passbudget.domain.models import CapacityProfile, Payload, ScenarioSnapshot

SPACECRAFT_TX_RESOURCE_SUFFIX = "-TX1"
RX_RESOURCE_SUFFIX = "-RX1"
PROFILE_SCHEMA_VERSION = "passbudget-profile-0.2"


@dataclass(frozen=True, slots=True)
class ProfileSpec:
    """One typed profile head plus the payload of its single published revision."""

    stable_key: str
    kind: ProfileKind
    name: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StationSpec:
    stable_key: str
    ground_station_key: str
    communication_key: str
    preference_rank: int
    minimum_elevation_udeg: int | None


@dataclass(frozen=True, slots=True)
class PayloadSpec:
    stable_key: str
    payload_type_key: str
    row: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CatalogGraph:
    profiles: tuple[ProfileSpec, ...]
    spacecraft_key: str
    policy_key: str | None
    stations: tuple[StationSpec, ...]
    payloads: tuple[PayloadSpec, ...]
    dependencies: tuple[tuple[str, str, str], ...]


def _communication_payload(profile: CapacityProfile) -> dict[str, Any]:
    fixed = profile.provider is CapacityProvider.FIXED_CAPACITY_PER_CONTACT
    return {
        "provider_kind": profile.provider.value,
        "fixed_capacity_bytes": profile.fixed_capacity_bytes,
        "rate_semantics": None
        if fixed
        else (profile.rate_semantics.value if profile.rate_semantics else None),
        "measurement_point": None if fixed else profile.measurement_point,
        "rate_scope": None if fixed else (profile.rate_scope.value if profile.rate_scope else None),
        "accounted_effects": [effect.value for effect in profile.accounted_effects],
        "acquisition_guard_us": profile.acquisition_guard_us,
        "release_guard_us": profile.release_guard_us,
        "reserve_kind": (
            "BYTE" if profile.byte_reserve else ("TIME" if profile.time_reserves else "NONE")
        ),
        "reserve_bytes": profile.byte_reserve if profile.byte_reserve else None,
        "capacity_accounting_layer": "LOGICAL_PAYLOAD",
        "rate_unknown": profile.rate_unknown,
        "evidence_state": profile.evidence_state.value,
        "source_revision_id": profile.source_revision_id,
        "rationale": profile.rationale,
        "timeline_segments": [
            {
                "segment_kind": "RATE",
                "ordinal": segment.ordinal,
                "start_offset_us": segment.start_offset_us,
                "end_offset_us": segment.end_offset_us,
                "rate_numerator_bits": segment.rate.numerator_bits,
                "rate_denominator_seconds": segment.rate.denominator_seconds,
            }
            for segment in sorted(profile.rate_segments, key=lambda item: item.ordinal)
        ]
        + [
            {
                "segment_kind": "TIME_RESERVE",
                "ordinal": ordinal,
                "start_offset_us": reserve.start_offset_us,
                "end_offset_us": reserve.end_offset_us,
                "rate_numerator_bits": None,
                "rate_denominator_seconds": None,
            }
            for ordinal, reserve in enumerate(
                sorted(profile.time_reserves, key=lambda item: item.start_offset_us)
            )
        ],
    }


def _payload_type_key(payload: Payload) -> str:
    if payload.segmentation is SegmentationKind.FIXED_CHUNK:
        return f"PT-CHUNK-{payload.chunk_size_bytes}"
    return "PT-ATOMIC"


def _payload_type_payload(payload: Payload) -> dict[str, Any]:
    return {
        "media_type": payload.media_type,
        "serializer_revision": "SYNTHETIC_LOGICAL_BYTES_V1",
        "segmentation": payload.segmentation.value,
        "fixed_chunk_bytes": payload.chunk_size_bytes,
        "resume_allowed": payload.resume_supported,
        "partial_product_usable": False,
        "completion_rule_revision": "INSTANCE_COMPLETE_V1",
    }


def decompose_snapshot(snapshot: ScenarioSnapshot) -> CatalogGraph:
    profiles: list[ProfileSpec] = []
    spacecraft_key = f"{snapshot.fixture_id}-SC"
    profiles.append(
        ProfileSpec(
            stable_key=spacecraft_key,
            kind=ProfileKind.SPACECRAFT,
            name=f"{snapshot.fixture_id} spacecraft",
            payload={
                "tx_resource_key": f"{spacecraft_key}{SPACECRAFT_TX_RESOURCE_SUFFIX}",
                "concurrent_tx_count": 1,
            },
        )
    )
    policy_key: str | None = None
    if snapshot.analysis_mode is AnalysisMode.QUEUE_AWARE and snapshot.policy_revision_id:
        policy_key = f"POLICY-{snapshot.policy_revision_id}"
        profiles.append(
            ProfileSpec(
                stable_key=policy_key,
                kind=ProfileKind.POLICY,
                name=snapshot.policy_revision_id,
                payload={
                    "policy_kind": "DEADLINE_SEVERITY",
                    "comparator_revision": snapshot.policy_revision_id,
                    "objective_revision": snapshot.policy_revision_id,
                    "tie_break_revision": "STATION_RANK_COMPLETION_START_LEXICAL_V1",
                    "starvation_guard": "NOT_APPLICABLE",
                },
            )
        )

    stations: list[StationSpec] = []
    for station in sorted(snapshot.stations, key=lambda item: item.stable_key):
        gs_key = f"GS-{station.stable_key}"
        comm_key = f"COMM-{station.stable_key}"
        site = station.site
        profiles.append(
            ProfileSpec(
                stable_key=gs_key,
                kind=ProfileKind.GROUND_STATION,
                name=station.stable_key,
                payload={
                    # ORBIT_DERIVED stations carry a WGS-84 site; synthetic injected contacts carry
                    # no station geometry, so the coordinate columns stay NULL rather than holding
                    # an invented position.
                    "latitude_udeg": None if site is None else site.latitude_udeg,
                    "longitude_udeg": None if site is None else site.longitude_east_udeg,
                    "ellipsoidal_height_mm": None if site is None else site.ellipsoidal_height_mm,
                    "rx_resource_key": f"{station.stable_key}{RX_RESOURCE_SUFFIX}",
                },
            )
        )
        profiles.append(
            ProfileSpec(
                stable_key=comm_key,
                kind=ProfileKind.COMMUNICATION,
                name=f"{station.stable_key} capacity",
                payload=_communication_payload(station.capacity),
            )
        )
        stations.append(
            StationSpec(
                stable_key=station.stable_key,
                ground_station_key=gs_key,
                communication_key=comm_key,
                preference_rank=station.preference_rank,
                minimum_elevation_udeg=None if site is None else site.minimum_elevation_udeg,
            )
        )

    payload_type_keys: dict[str, dict[str, Any]] = {}
    payloads: list[PayloadSpec] = []
    for payload in sorted(snapshot.payloads, key=lambda item: item.stable_key):
        type_key = _payload_type_key(payload)
        payload_type_keys.setdefault(type_key, _payload_type_payload(payload))
        payloads.append(
            PayloadSpec(
                stable_key=payload.stable_key,
                payload_type_key=type_key,
                row={
                    "display_name": payload.display_name or payload.stable_key,
                    "producer_kind": payload.producer_kind.value,
                    "ready_at": payload.ready_at.isoformat(),
                    "logical_size_bytes": payload.logical_size_bytes,
                    "storage_footprint_bytes": payload.storage_size_bytes,
                    "service_class": payload.service_class.value,
                    "mission_priority": payload.mission_priority,
                    "queue_sequence": payload.queue_sequence,
                    "deadline_at": (
                        payload.deadline_at.isoformat() if payload.deadline_at else None
                    ),
                    "deadline_target": (
                        payload.deadline_target.value if payload.deadline_target else None
                    ),
                    "post_deadline_action": (
                        payload.post_deadline_action.value if payload.post_deadline_action else None
                    ),
                    "expiry_at": payload.expiry_at.isoformat() if payload.expiry_at else None,
                    "severity_rank": payload.deadline_severity,
                    "bundle_key": payload.bundle_key,
                    "bundle_member_role": (
                        payload.bundle_member_role.value if payload.bundle_member_role else None
                    ),
                    "initial_storage_state": "GENERATED_AT_READY",
                },
            )
        )
    for type_key, type_payload in sorted(payload_type_keys.items()):
        profiles.append(
            ProfileSpec(
                stable_key=type_key,
                kind=ProfileKind.PAYLOAD_TYPE,
                name=type_key,
                payload=type_payload,
            )
        )

    dependencies = tuple(
        sorted(
            (item.predecessor_key, item.successor_key, item.kind.value)
            for item in snapshot.dependencies
        )
    )
    return CatalogGraph(
        profiles=tuple(sorted(profiles, key=lambda item: (item.kind.value, item.stable_key))),
        spacecraft_key=spacecraft_key,
        policy_key=policy_key,
        stations=tuple(stations),
        payloads=tuple(payloads),
        dependencies=dependencies,
    )
