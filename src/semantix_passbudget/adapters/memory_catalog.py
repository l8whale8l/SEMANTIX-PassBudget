"""In-memory catalog adapter.

Implements the same `CatalogRepository` contract as the PostgreSQL adapter so the lifecycle tests
and the DB-free CLI path exercise identical application code. It is volatile by design: restarting
the process clears it.
"""

from __future__ import annotations

from dataclasses import replace

from semantix_passbudget.domain.enums import ProfileKind
from semantix_passbudget.ports.catalog_repository import (
    ProfileHead,
    ProfileRevisionRecord,
    ScenarioHead,
    ScenarioRevisionRecord,
    SnapshotRecord,
)


class InMemoryCatalogRepository:
    def __init__(self) -> None:
        self._profiles: dict[str, ProfileHead] = {}
        self._profile_revisions: dict[str, ProfileRevisionRecord] = {}
        self._scenarios: dict[str, ScenarioHead] = {}
        self._scenario_revisions: dict[str, ScenarioRevisionRecord] = {}
        self._snapshots: dict[str, SnapshotRecord] = {}
        self._runs_by_scenario: dict[str, list[str]] = {}

    # -- profiles
    def add_profile(self, head: ProfileHead) -> None:
        self._profiles[head.profile_id] = head

    def get_profile(self, profile_id: str) -> ProfileHead | None:
        return self._profiles.get(profile_id)

    def set_profile_current_revision(self, profile_id: str, revision_id: str) -> None:
        head = self._profiles[profile_id]
        self._profiles[profile_id] = replace(head, current_revision_id=revision_id)

    def list_profiles(
        self, *, kind: ProfileKind | None = None, is_preset: bool | None = None
    ) -> tuple[ProfileHead, ...]:
        return tuple(
            sorted(
                (
                    head
                    for head in self._profiles.values()
                    if (kind is None or head.kind is kind)
                    and (is_preset is None or head.is_preset is is_preset)
                ),
                key=lambda item: (item.kind.value, item.stable_key),
            )
        )

    def add_profile_revision(self, revision: ProfileRevisionRecord) -> None:
        self._profile_revisions[revision.revision_id] = revision

    def get_profile_revision(self, revision_id: str) -> ProfileRevisionRecord | None:
        return self._profile_revisions.get(revision_id)

    def replace_profile_revision(self, revision: ProfileRevisionRecord) -> None:
        self._profile_revisions[revision.revision_id] = revision

    def list_profile_revisions(self, profile_id: str) -> tuple[ProfileRevisionRecord, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in self._profile_revisions.values()
                    if item.profile_id == profile_id
                ),
                key=lambda item: item.revision_no,
            )
        )

    # -- scenarios
    def add_scenario(self, head: ScenarioHead) -> None:
        self._scenarios[head.scenario_id] = head

    def get_scenario(self, scenario_id: str) -> ScenarioHead | None:
        return self._scenarios.get(scenario_id)

    def set_scenario_current_revision(self, scenario_id: str, revision_id: str) -> None:
        head = self._scenarios[scenario_id]
        self._scenarios[scenario_id] = replace(head, current_revision_id=revision_id)

    def list_scenarios(self, *, is_preset: bool | None = None) -> tuple[ScenarioHead, ...]:
        return tuple(
            sorted(
                (
                    head
                    for head in self._scenarios.values()
                    if is_preset is None or head.is_preset is is_preset
                ),
                key=lambda item: item.stable_key,
            )
        )

    def add_scenario_revision(self, revision: ScenarioRevisionRecord) -> None:
        self._scenario_revisions[revision.revision_id] = revision

    def get_scenario_revision(self, revision_id: str) -> ScenarioRevisionRecord | None:
        return self._scenario_revisions.get(revision_id)

    def replace_scenario_revision(self, revision: ScenarioRevisionRecord) -> None:
        self._scenario_revisions[revision.revision_id] = revision

    def list_scenario_revisions(self, scenario_id: str) -> tuple[ScenarioRevisionRecord, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in self._scenario_revisions.values()
                    if item.scenario_id == scenario_id
                ),
                key=lambda item: item.revision_no,
            )
        )

    # -- snapshots and runs
    def add_snapshot(self, snapshot: SnapshotRecord) -> None:
        self._snapshots[snapshot.snapshot_id] = snapshot

    def get_snapshot(self, snapshot_id: str) -> SnapshotRecord | None:
        return self._snapshots.get(snapshot_id)

    def record_run(self, scenario_id: str, run_id: str) -> None:
        self._runs_by_scenario.setdefault(scenario_id, []).append(run_id)

    def list_runs_for_scenario(self, scenario_id: str) -> tuple[str, ...]:
        return tuple(self._runs_by_scenario.get(scenario_id, ()))
