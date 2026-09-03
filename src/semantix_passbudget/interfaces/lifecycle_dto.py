"""Strict request/response DTOs for the P0 data-lifecycle endpoints.

These carry no calculation. They validate shape and delegate every rule to the application layer.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from semantix_passbudget.domain.enums import ProfileKind
from semantix_passbudget.interfaces.dto import FixtureDTO, StrictModel, enum_field

STABLE_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"


class CreateProfileRequest(StrictModel):
    stable_key: str = Field(pattern=STABLE_KEY_PATTERN)
    kind: ProfileKind = enum_field()
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    is_preset: bool = False


class CreateProfileRevisionRequest(StrictModel):
    label: str = Field(min_length=1, max_length=160)
    payload: dict[str, Any]
    change_note: str | None = Field(default=None, max_length=1000)
    based_on_revision_id: str | None = None


class ProfileRevisionResponse(StrictModel):
    revision_id: str
    profile_id: str
    profile_kind: ProfileKind = enum_field()
    revision_no: int
    lifecycle_status: str
    schema_version: str
    label: str
    change_note: str | None
    based_on_revision_id: str | None
    semantic_hash: str | None
    published_at: str | None


class ProfileResponse(StrictModel):
    profile_id: str
    stable_key: str
    kind: ProfileKind = enum_field()
    name: str
    description: str | None
    is_preset: bool
    current_revision_id: str | None
    revisions: list[ProfileRevisionResponse] = Field(default_factory=list)


class CreateScenarioRequest(StrictModel):
    stable_key: str = Field(pattern=STABLE_KEY_PATTERN)
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    is_preset: bool = False
    content: FixtureDTO


class CreateScenarioRevisionRequest(StrictModel):
    content: FixtureDTO | None = None
    based_on_revision_id: str | None = None


class CloneScenarioRevisionRequest(StrictModel):
    stable_key: str = Field(pattern=STABLE_KEY_PATTERN)
    name: str = Field(min_length=1, max_length=160)


class ScenarioRevisionResponse(StrictModel):
    revision_id: str
    scenario_id: str
    revision_no: int
    lifecycle_status: str
    schema_version: str
    based_on_revision_id: str | None
    semantic_hash: str | None
    published_at: str | None


class ScenarioResponse(StrictModel):
    scenario_id: str
    stable_key: str
    name: str
    description: str | None
    is_preset: bool
    current_revision_id: str | None
    revisions: list[ScenarioRevisionResponse] = Field(default_factory=list)
    recent_run_ids: list[str] = Field(default_factory=list)


class SnapshotResponse(StrictModel):
    snapshot_id: str
    scenario_revision_id: str
    schema_version: str
    canonicalization_revision: str
    input_snapshot_hash: str
    validation_status: str
    validation_code: str | None


class PresetsResponse(StrictModel):
    profiles: dict[str, list[dict[str, Any]]]
    scenarios: list[dict[str, Any]]
