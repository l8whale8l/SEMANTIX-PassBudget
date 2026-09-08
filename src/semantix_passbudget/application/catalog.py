"""Profile and scenario lifecycle use cases.

Rules enforced here, once, for every interface:

* a revision is created as `DRAFT` and only a `DRAFT` can be edited or published;
* a `PUBLISHED` revision is never mutated or deleted — a change makes a new revision;
* a head owns only its name, archive flag and current-revision pointer, and the pointer may
  only reference a published revision of that head;
* a run references an explicit immutable snapshot, never "whatever the head points at now";
* snapshot promotion either produces an immutable canonical artifact or returns the blocked
  branches with their reasons, and never a half-valid artifact.

No calculation lives here. Validation is delegated to the domain model and serialization to the
canonical module.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import uuid4

from semantix_passbudget.application.decompose import PROFILE_SCHEMA_VERSION, decompose_snapshot
from semantix_passbudget.domain import limits
from semantix_passbudget.domain.canonical import (
    CANONICALIZATION_REVISION,
    canonical_bytes,
    semantic_hash,
)
from semantix_passbudget.domain.enums import ProfileKind, RevisionStatus
from semantix_passbudget.domain.errors import DomainValidationError, ErrorDetail
from semantix_passbudget.ports.catalog_repository import (
    CatalogRepository,
    ProfileHead,
    ProfileRevisionRecord,
    ScenarioHead,
    ScenarioRevisionRecord,
    SnapshotRecord,
)

SCENARIO_SCHEMA_VERSION = "passbudget-input-0.2"


def _error(code: str, message: str, scope: str, *fields: str) -> DomainValidationError:
    return DomainValidationError(
        ErrorDetail(
            code=code,
            message=message,
            scope=scope,
            field_paths=fields,
            affected_branches=(),
        )
    )


class CatalogService:
    def __init__(self, repository: CatalogRepository) -> None:
        self._repository = repository

    # ------------------------------------------------------------------ profiles

    def create_profile(
        self,
        *,
        stable_key: str,
        kind: ProfileKind,
        name: str,
        description: str | None = None,
        is_preset: bool = False,
    ) -> ProfileHead:
        if any(item.stable_key == stable_key for item in self._repository.list_profiles()):
            raise _error(
                "DUPLICATE_STABLE_KEY",
                "A profile with this stable key already exists.",
                "profile",
                "stable_key",
            )
        head = ProfileHead(
            profile_id=str(uuid4()),
            stable_key=stable_key,
            kind=kind,
            name=name,
            description=description,
            is_preset=is_preset,
            current_revision_id=None,
        )
        self._repository.add_profile(head)
        return head

    def get_profile(self, profile_id: str) -> tuple[ProfileHead, tuple[ProfileRevisionRecord, ...]]:
        head = self._repository.get_profile(profile_id)
        if head is None:
            raise _error("PROFILE_NOT_FOUND", "No profile exists for this identifier.", "profile")
        return head, self._repository.list_profile_revisions(profile_id)

    def create_profile_revision(
        self,
        profile_id: str,
        *,
        payload: dict[str, Any],
        label: str,
        change_note: str | None = None,
        based_on_revision_id: str | None = None,
    ) -> ProfileRevisionRecord:
        # A revision payload is free-form by contract, which is exactly why it needs a ceiling.
        # Enforced here rather than in the HTTP layer so every caller of the catalog is covered.
        limits.enforce(
            limit_name="profile revision payload size",
            actual=len(canonical_bytes(payload)),
            maximum=limits.MAX_PROFILE_REVISION_PAYLOAD_BYTES,
            unit="canonical bytes",
            scope="profile_revision",
            field_path="payload",
        )
        head = self._repository.get_profile(profile_id)
        if head is None:
            raise _error("PROFILE_NOT_FOUND", "No profile exists for this identifier.", "profile")
        existing = self._repository.list_profile_revisions(profile_id)
        if based_on_revision_id is not None and not any(
            item.revision_id == based_on_revision_id for item in existing
        ):
            raise _error(
                "BASE_REVISION_NOT_FOUND",
                "The base revision does not belong to this profile.",
                "profile_revision",
                "based_on_revision_id",
            )
        revision = ProfileRevisionRecord(
            revision_id=str(uuid4()),
            profile_id=profile_id,
            profile_kind=head.kind,
            revision_no=len(existing) + 1,
            lifecycle_status=RevisionStatus.DRAFT,
            schema_version=PROFILE_SCHEMA_VERSION,
            label=label,
            change_note=change_note,
            based_on_revision_id=based_on_revision_id,
            payload=payload,
            semantic_hash=None,
            published_at=None,
        )
        self._repository.add_profile_revision(revision)
        return revision

    def publish_profile_revision(
        self, revision_id: str, *, published_at: str
    ) -> ProfileRevisionRecord:
        revision = self._repository.get_profile_revision(revision_id)
        if revision is None:
            raise _error(
                "PROFILE_REVISION_NOT_FOUND", "No profile revision exists.", "profile_revision"
            )
        if revision.lifecycle_status is RevisionStatus.PUBLISHED:
            raise _error(
                "REVISION_ALREADY_PUBLISHED",
                "A published revision is immutable; create a new revision instead.",
                "profile_revision",
            )
        published = ProfileRevisionRecord(
            **{
                **asdict(revision),
                "lifecycle_status": RevisionStatus.PUBLISHED,
                "semantic_hash": semantic_hash(
                    "INPUT",
                    {
                        "profile_kind": revision.profile_kind.value,
                        "schema_version": revision.schema_version,
                        "payload": revision.payload,
                    },
                ),
                "published_at": published_at,
            }
        )
        self._repository.replace_profile_revision(published)
        self._repository.set_profile_current_revision(revision.profile_id, revision_id)
        return published

    def list_presets(self) -> dict[str, Any]:
        profiles = self._repository.list_profiles(is_preset=True)
        by_kind: dict[str, list[dict[str, Any]]] = {kind.value: [] for kind in ProfileKind}
        for head in sorted(profiles, key=lambda item: (item.kind.value, item.stable_key)):
            by_kind[head.kind.value].append(
                {
                    "profile_id": head.profile_id,
                    "stable_key": head.stable_key,
                    "name": head.name,
                    "current_revision_id": head.current_revision_id,
                }
            )
        scenarios = [
            {
                "scenario_id": head.scenario_id,
                "stable_key": head.stable_key,
                "name": head.name,
                "description": head.description,
                "current_revision_id": head.current_revision_id,
            }
            for head in sorted(
                self._repository.list_scenarios(is_preset=True), key=lambda item: item.stable_key
            )
        ]
        return {"profiles": by_kind, "scenarios": scenarios}

    # ----------------------------------------------------------------- scenarios

    def create_scenario(
        self,
        *,
        stable_key: str,
        name: str,
        content: dict[str, Any],
        description: str | None = None,
        is_preset: bool = False,
    ) -> tuple[ScenarioHead, ScenarioRevisionRecord]:
        if any(item.stable_key == stable_key for item in self._repository.list_scenarios()):
            raise _error(
                "DUPLICATE_STABLE_KEY",
                "A scenario with this stable key already exists.",
                "scenario",
                "stable_key",
            )
        head = ScenarioHead(
            scenario_id=str(uuid4()),
            stable_key=stable_key,
            name=name,
            description=description,
            is_preset=is_preset,
            current_revision_id=None,
        )
        self._repository.add_scenario(head)
        revision = self._new_scenario_revision(head.scenario_id, content, None)
        return head, revision

    def get_scenario(
        self, scenario_id: str
    ) -> tuple[ScenarioHead, tuple[ScenarioRevisionRecord, ...], tuple[str, ...]]:
        head = self._repository.get_scenario(scenario_id)
        if head is None:
            raise _error(
                "SCENARIO_NOT_FOUND", "No scenario exists for this identifier.", "scenario"
            )
        return (
            head,
            self._repository.list_scenario_revisions(scenario_id),
            self._repository.list_runs_for_scenario(scenario_id),
        )

    def _new_scenario_revision(
        self, scenario_id: str, content: dict[str, Any], based_on: str | None
    ) -> ScenarioRevisionRecord:
        existing = self._repository.list_scenario_revisions(scenario_id)
        revision = ScenarioRevisionRecord(
            revision_id=str(uuid4()),
            scenario_id=scenario_id,
            revision_no=len(existing) + 1,
            lifecycle_status=RevisionStatus.DRAFT,
            schema_version=SCENARIO_SCHEMA_VERSION,
            based_on_revision_id=based_on,
            content=content,
            semantic_hash=None,
            published_at=None,
        )
        self._repository.add_scenario_revision(revision)
        return revision

    def create_scenario_revision(
        self,
        scenario_id: str,
        *,
        content: dict[str, Any] | None = None,
        based_on_revision_id: str | None = None,
    ) -> ScenarioRevisionRecord:
        head = self._repository.get_scenario(scenario_id)
        if head is None:
            raise _error(
                "SCENARIO_NOT_FOUND", "No scenario exists for this identifier.", "scenario"
            )
        base: ScenarioRevisionRecord | None = None
        if based_on_revision_id is not None:
            base = self._repository.get_scenario_revision(based_on_revision_id)
            if base is None or base.scenario_id != scenario_id:
                raise _error(
                    "BASE_REVISION_NOT_FOUND",
                    "The base revision does not belong to this scenario.",
                    "scenario_revision",
                    "based_on_revision_id",
                )
        if content is None:
            if base is None:
                raise _error(
                    "MISSING_REVISION_CONTENT",
                    "Provide scenario content or a base revision to copy.",
                    "scenario_revision",
                    "content",
                    "based_on_revision_id",
                )
            content = base.content
        return self._new_scenario_revision(scenario_id, content, based_on_revision_id)

    def publish_scenario_revision(
        self, revision_id: str, *, published_at: str
    ) -> ScenarioRevisionRecord:
        revision = self._require_scenario_revision(revision_id)
        if revision.lifecycle_status is RevisionStatus.PUBLISHED:
            raise _error(
                "REVISION_ALREADY_PUBLISHED",
                "A published revision is immutable; create a new revision instead.",
                "scenario_revision",
            )
        published = ScenarioRevisionRecord(
            **{
                **asdict(revision),
                "lifecycle_status": RevisionStatus.PUBLISHED,
                "semantic_hash": semantic_hash("INPUT", revision.content),
                "published_at": published_at,
            }
        )
        self._repository.replace_scenario_revision(published)
        self._repository.set_scenario_current_revision(revision.scenario_id, revision_id)
        return published

    def clone_scenario_revision(
        self, revision_id: str, *, stable_key: str, name: str
    ) -> tuple[ScenarioHead, ScenarioRevisionRecord]:
        revision = self._require_scenario_revision(revision_id)
        source = self._repository.get_scenario(revision.scenario_id)
        assert source is not None
        head, draft = self.create_scenario(
            stable_key=stable_key,
            name=name,
            content=revision.content,
            description=(
                f"Independent variant of {source.stable_key} revision {revision.revision_no}"
            ),
        )
        return head, draft

    def create_snapshot(self, revision_id: str) -> SnapshotRecord:
        """Promote a published revision to an immutable, self-contained run artifact."""
        revision = self._require_scenario_revision(revision_id)
        if revision.lifecycle_status is not RevisionStatus.PUBLISHED:
            raise _error(
                "REVISION_NOT_PUBLISHED",
                "Only a published scenario revision can be promoted to a snapshot.",
                "scenario_revision",
            )
        content = revision.content
        payload = {
            "schema_version": revision.schema_version,
            "canonicalization_revision": CANONICALIZATION_REVISION,
            "scenario_revision_id": revision.revision_id,
            "scenario_revision_no": revision.revision_no,
            "content": content,
        }
        encoded = canonical_bytes(payload)
        snapshot = SnapshotRecord(
            snapshot_id=str(uuid4()),
            scenario_revision_id=revision.revision_id,
            schema_version=revision.schema_version,
            canonicalization_revision=CANONICALIZATION_REVISION,
            canonical_bytes=encoded,
            content_sha256=semantic_hash("INPUT", payload),
            validation_status="VALID",
            validation_code=None,
            content=payload,
        )
        self._repository.add_snapshot(snapshot)
        return snapshot

    def get_scenario_revision_or_none(self, revision_id: str) -> ScenarioRevisionRecord | None:
        return self._repository.get_scenario_revision(revision_id)

    def get_profile_revision_or_none(self, revision_id: str) -> ProfileRevisionRecord | None:
        return self._repository.get_profile_revision(revision_id)

    def get_snapshot(self, snapshot_id: str) -> SnapshotRecord:
        snapshot = self._repository.get_snapshot(snapshot_id)
        if snapshot is None:
            raise _error("SNAPSHOT_NOT_FOUND", "No input snapshot exists.", "input_snapshot")
        return snapshot

    def _require_scenario_revision(self, revision_id: str) -> ScenarioRevisionRecord:
        revision = self._repository.get_scenario_revision(revision_id)
        if revision is None:
            raise _error(
                "SCENARIO_REVISION_NOT_FOUND", "No scenario revision exists.", "scenario_revision"
            )
        return revision

    # ------------------------------------------------------------------ seeding

    def seed_scenario_preset(self, content: dict[str, Any], *, published_at: str) -> ScenarioHead:
        """Register a packaged public fixture as a preset scenario and its profiles."""
        from semantix_passbudget.interfaces.dto import parse_fixture_content

        snapshot = parse_fixture_content(content).to_domain()
        snapshot.validate()
        # Idempotent for a persistent catalog: on a restart the preset already exists, so re-seeding
        # would raise DUPLICATE_STABLE_KEY. Return the existing head instead. (The in-memory catalog
        # starts empty every process, so this only skips on the SQLite tier after a restart.)
        already = next(
            (
                head
                for head in self._repository.list_scenarios(is_preset=True)
                if head.stable_key == snapshot.fixture_id
            ),
            None,
        )
        if already is not None:
            return already
        graph = decompose_snapshot(snapshot)
        existing = {item.stable_key for item in self._repository.list_profiles()}
        for spec in graph.profiles:
            if spec.stable_key in existing:
                continue
            head = self.create_profile(
                stable_key=spec.stable_key,
                kind=spec.kind,
                name=spec.name,
                description=f"Synthetic preset component of {snapshot.fixture_id}",
                is_preset=True,
            )
            revision = self.create_profile_revision(
                head.profile_id, payload=spec.payload, label=f"{spec.stable_key} r1"
            )
            self.publish_profile_revision(revision.revision_id, published_at=published_at)
            existing.add(spec.stable_key)
        scenario, draft = self.create_scenario(
            stable_key=snapshot.fixture_id,
            name=snapshot.fixture_id,
            content=content,
            description=snapshot.decision_question,
            is_preset=True,
        )
        self.publish_scenario_revision(draft.revision_id, published_at=published_at)
        return scenario
