from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .enums import CalculationStatus, DecisionGrade, ReasonCode
from .time import TimeInterval


def interval_dict(interval: TimeInterval | None) -> dict[str, str] | None:
    if interval is None:
        return None
    return {"start": interval.start.isoformat(), "end": interval.end.isoformat()}


@dataclass(frozen=True, slots=True)
class ContactResult:
    stable_key: str
    station_key: str
    true_interval: TimeInterval
    modeled_interval: TimeInterval | None
    capacity_bytes: int | None
    calculation_status: CalculationStatus
    decision_grade: DecisionGrade
    reason_codes: tuple[ReasonCode, ...]

    def geometric_dict(self) -> dict[str, Any]:
        return {
            "stable_key": f"geometric/{self.stable_key}",
            "station_key": self.station_key,
            "true_aos": self.true_interval.start.isoformat(),
            "true_los": self.true_interval.end.isoformat(),
            "calculation_status": CalculationStatus.COMPUTED.value,
            "decision_grade": DecisionGrade.CONCEPT_ONLY.value,
        }

    def modeled_dict(self) -> dict[str, Any]:
        return {
            "stable_key": f"modeled/{self.stable_key}",
            "geometric_stable_key": f"geometric/{self.stable_key}",
            "station_key": self.station_key,
            "usable_start": (
                self.modeled_interval.start.isoformat() if self.modeled_interval else None
            ),
            "usable_end": self.modeled_interval.end.isoformat() if self.modeled_interval else None,
            "calculation_status": self.calculation_status.value,
            "decision_grade": self.decision_grade.value,
            "reason_codes": [{"code": code.value} for code in self.reason_codes],
        }

    def candidate_dict(self) -> dict[str, Any]:
        return {
            "stable_key": f"candidate/{self.stable_key}",
            "modeled_stable_key": f"modeled/{self.stable_key}",
            "station_key": self.station_key,
            "usable_start": (
                self.modeled_interval.start.isoformat() if self.modeled_interval else None
            ),
            "usable_end": self.modeled_interval.end.isoformat() if self.modeled_interval else None,
            "capacity_bytes": self.capacity_bytes,
            "calculation_status": self.calculation_status.value,
            "decision_grade": self.decision_grade.value,
            "reason_codes": [{"code": code.value} for code in self.reason_codes],
        }
