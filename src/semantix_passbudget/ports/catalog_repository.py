"""Catalog persistence port.

The application layer never talks to SQLAlchemy or to a dict; it talks to this protocol. The
in-memory adapter and the PostgreSQL adapter implement the same contract, so the lifecycle rules
(draft/publish immutability, explicit revision selection, immutable snapshots) live in exactly one
place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from semantix_passbudget.domain.enums import ProfileKind, RevisionStatus


@dataclass(frozen=True, slots=True)
class ProfileHead:
    profile_id: str
    stable_key: str
    kind: ProfileKind
    name: str
    description: str | None
    is_preset: bool
    current_revision_id: str | None
    archived: bool = False


@dataclass(frozen=True, slots=True)
class ProfileRevisionRecord:
    revision_id: str
    profile_id: str
    profile_kind: ProfileKind
    revision_no: int
    lifecycle_status: RevisionStatus
    schema_version: str
    label: str
    change_note: str | None
    based_on_revision_id: str | None
    payload: dict[str, Any]
    semantic_hash: str | None
    published_at: str | None


@dataclass(frozen=True, slots=True)
class ScenarioHead:
    scenario_id: str
    stable_key: str
    name: str
    description: str | None
    is_preset: bool
    current_revision_id: str | None
    archived: bool = False


@dataclass(frozen=True, slots=True)
class ScenarioRevisionRecord:
    revision_id: str
    scenario_id: str
    revision_no: int
    lifecycle_status: RevisionStatus
    schema_version: str
    based_on_revision_id: str | None
    content: dict[str, Any]
    semantic_hash: str | None
    published_at: str | None


@dataclass(frozen=True, slots=True)
class SnapshotRecord:
    snapshot_id: str
    scenario_revision_id: str
    schema_version: str
    canonicalization_revision: str
    canonical_bytes: bytes
    content_sha256: str
    validation_status: str
    validation_code: str | None
    content: dict[str, Any]


class CatalogRepository(Protocol):
    def add_profile(self, head: ProfileHead) -> None: ...

    def get_profile(self, profile_id: str) -> ProfileHead | None: ...

    def set_profile_current_revision(self, profile_id: str, revision_id: str) -> None: ...

    def list_profiles(
        self, *, kind: ProfileKind | None = None, is_preset: bool | None = None
    ) -> tuple[ProfileHead, ...]: ...

    def add_profile_revision(self, revision: ProfileRevisionRecord) -> None: ...

    def get_profile_revision(self, revision_id: str) -> ProfileRevisionRecord | None: ...

    def replace_profile_revision(self, revision: ProfileRevisionRecord) -> None: ...

    def list_profile_revisions(self, profile_id: str) -> tuple[ProfileRevisionRecord, ...]: ...

    def add_scenario(self, head: ScenarioHead) -> None: ...

    def get_scenario(self, scenario_id: str) -> ScenarioHead | None: ...

    def set_scenario_current_revision(self, scenario_id: str, revision_id: str) -> None: ...

    def list_scenarios(self, *, is_preset: bool | None = None) -> tuple[ScenarioHead, ...]: ...

    def add_scenario_revision(self, revision: ScenarioRevisionRecord) -> None: ...

    def get_scenario_revision(self, revision_id: str) -> ScenarioRevisionRecord | None: ...

    def replace_scenario_revision(self, revision: ScenarioRevisionRecord) -> None: ...

    def list_scenario_revisions(self, scenario_id: str) -> tuple[ScenarioRevisionRecord, ...]: ...

    def add_snapshot(self, snapshot: SnapshotRecord) -> None: ...

    def get_snapshot(self, snapshot_id: str) -> SnapshotRecord | None: ...

    def record_run(self, scenario_id: str, run_id: str) -> None: ...

    def list_runs_for_scenario(self, scenario_id: str) -> tuple[str, ...]: ...
