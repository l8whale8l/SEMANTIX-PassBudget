from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from semantix_passbudget.domain.models import ScenarioSnapshot
from semantix_passbudget.ports.persisted_rows import PersistedRows


@dataclass(frozen=True, slots=True)
class StoredRun:
    run_id: str
    status: str
    input_snapshot_hash: str
    result_content_hash: str
    run_record_hash: str
    stages: tuple[dict[str, Any], ...]
    result: dict[str, Any]
    #: Resolved input the run was computed from. A persistence adapter needs it to write the
    #: typed catalog rows; the in-memory adapter simply carries it.
    snapshot: ScenarioSnapshot | None = None
    #: Canonical semantic input payload behind `input_snapshot_hash`.
    input_snapshot_payload: dict[str, Any] = field(default_factory=dict)
    #: Typed rows read back from a relational store, when the run came from one.
    persisted_rows: PersistedRows | None = None

    def metadata_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "input_snapshot_hash": self.input_snapshot_hash,
            "result_content_hash": self.result_content_hash,
            "run_record_hash": self.run_record_hash,
            "stages": list(self.stages),
        }


class RunRepository(Protocol):
    def add(self, run: StoredRun) -> None: ...

    def get(self, run_id: str) -> StoredRun | None: ...
