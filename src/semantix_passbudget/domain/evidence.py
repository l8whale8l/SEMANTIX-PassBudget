from __future__ import annotations

from dataclasses import dataclass

from .enums import EvidenceKind, EvidenceState, OriginKind, PresenceState, ValueState
from .errors import DomainValidationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class ResolvedEvidenceValue[T]:
    presence_state: PresenceState
    value_state: ValueState | None
    value: T | None
    canonical_unit: str | None
    evidence_state: EvidenceState | None
    evidence_kind: EvidenceKind | None
    source_revision_id: str | None
    rationale: str | None
    origin_kind: OriginKind

    def __post_init__(self) -> None:
        omitted = self.presence_state is PresenceState.OMITTED
        if omitted and any(
            item is not None
            for item in (self.value_state, self.value, self.evidence_state, self.evidence_kind)
        ):
            self._invalid("OMITTED values cannot carry value or evidence state.")
        if self.value_state is ValueState.KNOWN:
            if self.value is None or self.evidence_state not in {
                EvidenceState.CONFIRMED,
                EvidenceState.PROVISIONAL,
                EvidenceState.PROXY,
            }:
                self._invalid("KNOWN requires a value and a usable evidence state.")
        elif (
            self.value_state in {ValueState.UNKNOWN, ValueState.NOT_APPLICABLE}
            and self.value is not None
        ):
            self._invalid("UNKNOWN and NOT_APPLICABLE require null value.")
        if self.evidence_state is EvidenceState.PROXY and (
            not self.source_revision_id or not self.rationale
        ):
            self._invalid("PROXY requires source revision and rationale.")

    @staticmethod
    def _invalid(message: str) -> None:
        raise DomainValidationError(
            ErrorDetail(
                code="INVALID_EVIDENCE_COMBINATION",
                message=message,
                scope="evidence",
                field_paths=("evidence",),
                affected_branches=("dependent",),
            )
        )
