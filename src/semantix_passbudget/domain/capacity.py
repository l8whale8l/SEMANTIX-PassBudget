from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .enums import CalculationStatus, CapacityProvider, DecisionGrade, EvidenceState, ReasonCode
from .models import CapacityProfile, SyntheticContact
from .time import TimeInterval, UtcInstant


@dataclass(frozen=True, slots=True)
class ModeledCapacity:
    modeled_interval: TimeInterval | None
    capacity_bytes: int | None
    status: CalculationStatus
    grade: DecisionGrade
    reason_codes: tuple[ReasonCode, ...]


def grade_for_evidence(evidence_state: EvidenceState) -> DecisionGrade:
    if evidence_state is EvidenceState.CONFIRMED:
        return DecisionGrade.VERIFIED
    if evidence_state is EvidenceState.PROVISIONAL:
        return DecisionGrade.ENGINEERING_ESTIMATE
    if evidence_state is EvidenceState.PROXY:
        return DecisionGrade.CONCEPT_ONLY
    return DecisionGrade.BLOCKED


def calculate_contact_capacity(
    contact: SyntheticContact,
    profile: CapacityProfile,
    analysis_window: TimeInterval,
) -> ModeledCapacity:
    grade = grade_for_evidence(profile.evidence_state)
    true_start = contact.true_interval.start.microseconds
    true_end = contact.true_interval.end.microseconds
    guarded_start = true_start + profile.acquisition_guard_us
    guarded_end = true_end - profile.release_guard_us
    if guarded_start >= guarded_end:
        return ModeledCapacity(
            modeled_interval=None,
            capacity_bytes=0,
            status=CalculationStatus.KNOWN_ZERO,
            grade=grade,
            reason_codes=(ReasonCode.GUARD_EXCEEDS_WINDOW,),
        )
    guarded = TimeInterval(UtcInstant(guarded_start), UtcInstant(guarded_end))
    modeled = guarded.intersect(analysis_window)
    if modeled is None:
        return ModeledCapacity(
            modeled_interval=None,
            capacity_bytes=0,
            status=CalculationStatus.KNOWN_ZERO,
            grade=grade,
            reason_codes=(),
        )
    if profile.provider is CapacityProvider.FIXED_CAPACITY_PER_CONTACT:
        return ModeledCapacity(
            modeled_interval=modeled,
            capacity_bytes=profile.fixed_capacity_bytes,
            status=(
                CalculationStatus.KNOWN_ZERO
                if profile.fixed_capacity_bytes == 0
                else CalculationStatus.COMPUTED
            ),
            grade=grade,
            reason_codes=(),
        )
    if profile.rate_unknown:
        return ModeledCapacity(
            modeled_interval=modeled,
            capacity_bytes=None,
            status=CalculationStatus.BLOCKED,
            grade=DecisionGrade.BLOCKED,
            reason_codes=(ReasonCode.RATE_UNKNOWN,),
        )

    clip_start_offset_us = modeled.start.microseconds - guarded.start.microseconds
    clip_end_offset_us = modeled.end.microseconds - guarded.start.microseconds
    total_bits = Fraction(0)
    for segment in sorted(profile.rate_segments, key=lambda item: item.ordinal):
        overlap_start = max(clip_start_offset_us, segment.start_offset_us)
        overlap_end = min(clip_end_offset_us, segment.end_offset_us)
        if overlap_start < overlap_end:
            reserved_us = sum(
                max(
                    0,
                    min(overlap_end, reserve.end_offset_us)
                    - max(overlap_start, reserve.start_offset_us),
                )
                for reserve in profile.time_reserves
            )
            duration_seconds = Fraction(overlap_end - overlap_start - reserved_us, 1_000_000)
            total_bits += segment.rate.fraction * duration_seconds
    if profile.active_efficiency is not None:
        total_bits *= profile.active_efficiency
    bytes_before_reserve = total_bits.numerator // (total_bits.denominator * 8)
    capacity_bytes = max(0, bytes_before_reserve - profile.byte_reserve)
    return ModeledCapacity(
        modeled_interval=modeled,
        capacity_bytes=capacity_bytes,
        status=(
            CalculationStatus.KNOWN_ZERO if capacity_bytes == 0 else CalculationStatus.COMPUTED
        ),
        grade=grade,
        reason_codes=(),
    )
