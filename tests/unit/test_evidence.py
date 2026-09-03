import pytest

from semantix_passbudget.domain.canonical import canonical_bytes
from semantix_passbudget.domain.enums import (
    EvidenceKind,
    EvidenceState,
    OriginKind,
    PresenceState,
    ValueState,
)
from semantix_passbudget.domain.errors import DomainValidationError
from semantix_passbudget.domain.evidence import ResolvedEvidenceValue


def _resolved(
    presence: PresenceState, value_state: ValueState | None, value: int | None
) -> ResolvedEvidenceValue[int]:
    known = value_state is ValueState.KNOWN
    return ResolvedEvidenceValue(
        presence_state=presence,
        value_state=value_state,
        value=value,
        canonical_unit="BYTE" if known else None,
        evidence_state=EvidenceState.CONFIRMED if known else None,
        evidence_kind=EvidenceKind.USER_ASSUMPTION if known else None,
        source_revision_id="TEST-R1" if known else None,
        rationale=None,
        origin_kind=OriginKind.EXPLICIT,
    )


def test_zero_unknown_omitted_na_and_defaulted_zero_are_distinct() -> None:
    states = (
        _resolved(PresenceState.PROVIDED, ValueState.KNOWN, 0),
        _resolved(PresenceState.PROVIDED, ValueState.UNKNOWN, None),
        _resolved(PresenceState.OMITTED, None, None),
        _resolved(PresenceState.PROVIDED, ValueState.NOT_APPLICABLE, None),
        _resolved(PresenceState.DEFAULTED, ValueState.KNOWN, 0),
    )
    encoded = {
        canonical_bytes(
            {
                "presence": state.presence_state.value,
                "value_state": state.value_state.value if state.value_state else None,
                "value": state.value,
            }
        )
        for state in states
    }
    assert len(encoded) == 5


def test_source_less_proxy_is_invalid() -> None:
    with pytest.raises(DomainValidationError):
        ResolvedEvidenceValue(
            presence_state=PresenceState.PROVIDED,
            value_state=ValueState.KNOWN,
            value=1,
            canonical_unit="BYTE",
            evidence_state=EvidenceState.PROXY,
            evidence_kind=EvidenceKind.ANALOG_PROXY,
            source_revision_id=None,
            rationale=None,
            origin_kind=OriginKind.EXPLICIT,
        )
