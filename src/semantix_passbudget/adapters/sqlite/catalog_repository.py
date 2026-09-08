"""SQLite catalog persistence: scenarios, revisions and snapshots that survive a restart.

Implements the same `CatalogRepository` contract as the in-memory adapter, storing the port's
opaque bodies (profile payloads, scenario content, snapshot content) as JSON in the `catalog_*`
tables added in schema v2. It stores and reads exactly what the application produced; it enforces
no lifecycle rule of its own (those live in `application/catalog.py`) and derives no hash.

A short-lived connection is opened per operation, matching `SqliteRunRepository`: SQLite
connections are not safe to share between threads, and the API serves requests from a worker pool.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from semantix_passbudget.adapters.sqlite.schema import connect, migrate
from semantix_passbudget.domain.enums import ProfileKind, RevisionStatus
from semantix_passbudget.ports.catalog_repository import (
    ProfileHead,
    ProfileRevisionRecord,
    ScenarioHead,
    ScenarioRevisionRecord,
    SnapshotRecord,
)


class SqliteCatalogError(RuntimeError):
    """Redacted local catalog-persistence failure. The driver exception is not chained."""


@contextmanager
def _redacted(operation: str) -> Iterator[None]:
    try:
        yield
    except sqlite3.Error:
        raise SqliteCatalogError(f"local catalog operation failed: {operation}") from None


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load(text: Any) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(str(text))
    return loaded


class SqliteCatalogRepository:
    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        with self._connection() as connection:
            migrate(connection)

    @property
    def path(self) -> str:
        return self._path

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = connect(self._path)
        try:
            yield connection
        finally:
            connection.close()

    # ------------------------------------------------------------------ profiles

    def add_profile(self, head: ProfileHead) -> None:
        with _redacted("add profile"), self._connection() as connection:
            connection.execute(
                "INSERT INTO catalog_profile (profile_id, stable_key, kind, name, description,"
                " is_preset, current_revision_id, archived) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    head.profile_id,
                    head.stable_key,
                    head.kind.value,
                    head.name,
                    head.description,
                    1 if head.is_preset else 0,
                    head.current_revision_id,
                    1 if head.archived else 0,
                ),
            )

    def get_profile(self, profile_id: str) -> ProfileHead | None:
        with _redacted("get profile"), self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM catalog_profile WHERE profile_id = ?", (profile_id,)
            ).fetchone()
        return None if row is None else self._profile_head(row)

    def set_profile_current_revision(self, profile_id: str, revision_id: str) -> None:
        with _redacted("set profile current revision"), self._connection() as connection:
            connection.execute(
                "UPDATE catalog_profile SET current_revision_id = ? WHERE profile_id = ?",
                (revision_id, profile_id),
            )

    def list_profiles(
        self, *, kind: ProfileKind | None = None, is_preset: bool | None = None
    ) -> tuple[ProfileHead, ...]:
        clauses: list[str] = []
        params: list[Any] = []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind.value)
        if is_preset is not None:
            clauses.append("is_preset = ?")
            params.append(1 if is_preset else 0)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with _redacted("list profiles"), self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM catalog_profile{where} ORDER BY kind, stable_key", params
            ).fetchall()
        return tuple(self._profile_head(row) for row in rows)

    def add_profile_revision(self, revision: ProfileRevisionRecord) -> None:
        with _redacted("add profile revision"), self._connection() as connection:
            connection.execute(
                "INSERT INTO catalog_profile_revision (revision_id, profile_id, profile_kind,"
                " revision_no, lifecycle_status, schema_version, label, change_note,"
                " based_on_revision_id, payload_json, semantic_hash, published_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    revision.revision_id,
                    revision.profile_id,
                    revision.profile_kind.value,
                    revision.revision_no,
                    revision.lifecycle_status.value,
                    revision.schema_version,
                    revision.label,
                    revision.change_note,
                    revision.based_on_revision_id,
                    _json(revision.payload),
                    revision.semantic_hash,
                    revision.published_at,
                ),
            )

    def get_profile_revision(self, revision_id: str) -> ProfileRevisionRecord | None:
        with _redacted("get profile revision"), self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM catalog_profile_revision WHERE revision_id = ?", (revision_id,)
            ).fetchone()
        return None if row is None else self._profile_revision(row)

    def replace_profile_revision(self, revision: ProfileRevisionRecord) -> None:
        with _redacted("replace profile revision"), self._connection() as connection:
            connection.execute(
                "UPDATE catalog_profile_revision SET lifecycle_status = ?, semantic_hash = ?,"
                " published_at = ?, payload_json = ? WHERE revision_id = ?",
                (
                    revision.lifecycle_status.value,
                    revision.semantic_hash,
                    revision.published_at,
                    _json(revision.payload),
                    revision.revision_id,
                ),
            )

    def list_profile_revisions(self, profile_id: str) -> tuple[ProfileRevisionRecord, ...]:
        with _redacted("list profile revisions"), self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM catalog_profile_revision WHERE profile_id = ? ORDER BY revision_no",
                (profile_id,),
            ).fetchall()
        return tuple(self._profile_revision(row) for row in rows)

    # ------------------------------------------------------------------ scenarios

    def add_scenario(self, head: ScenarioHead) -> None:
        with _redacted("add scenario"), self._connection() as connection:
            connection.execute(
                "INSERT INTO catalog_scenario (scenario_id, stable_key, name, description,"
                " is_preset, current_revision_id, archived) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    head.scenario_id,
                    head.stable_key,
                    head.name,
                    head.description,
                    1 if head.is_preset else 0,
                    head.current_revision_id,
                    1 if head.archived else 0,
                ),
            )

    def get_scenario(self, scenario_id: str) -> ScenarioHead | None:
        with _redacted("get scenario"), self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM catalog_scenario WHERE scenario_id = ?", (scenario_id,)
            ).fetchone()
        return None if row is None else self._scenario_head(row)

    def set_scenario_current_revision(self, scenario_id: str, revision_id: str) -> None:
        with _redacted("set scenario current revision"), self._connection() as connection:
            connection.execute(
                "UPDATE catalog_scenario SET current_revision_id = ? WHERE scenario_id = ?",
                (revision_id, scenario_id),
            )

    def list_scenarios(self, *, is_preset: bool | None = None) -> tuple[ScenarioHead, ...]:
        where = "" if is_preset is None else " WHERE is_preset = ?"
        params: tuple[Any, ...] = () if is_preset is None else (1 if is_preset else 0,)
        with _redacted("list scenarios"), self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM catalog_scenario{where} ORDER BY stable_key", params
            ).fetchall()
        return tuple(self._scenario_head(row) for row in rows)

    def add_scenario_revision(self, revision: ScenarioRevisionRecord) -> None:
        with _redacted("add scenario revision"), self._connection() as connection:
            connection.execute(
                "INSERT INTO catalog_scenario_revision (revision_id, scenario_id, revision_no,"
                " lifecycle_status, schema_version, based_on_revision_id, content_json,"
                " semantic_hash, published_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    revision.revision_id,
                    revision.scenario_id,
                    revision.revision_no,
                    revision.lifecycle_status.value,
                    revision.schema_version,
                    revision.based_on_revision_id,
                    _json(revision.content),
                    revision.semantic_hash,
                    revision.published_at,
                ),
            )

    def get_scenario_revision(self, revision_id: str) -> ScenarioRevisionRecord | None:
        with _redacted("get scenario revision"), self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM catalog_scenario_revision WHERE revision_id = ?", (revision_id,)
            ).fetchone()
        return None if row is None else self._scenario_revision(row)

    def replace_scenario_revision(self, revision: ScenarioRevisionRecord) -> None:
        with _redacted("replace scenario revision"), self._connection() as connection:
            connection.execute(
                "UPDATE catalog_scenario_revision SET lifecycle_status = ?, semantic_hash = ?,"
                " published_at = ?, content_json = ? WHERE revision_id = ?",
                (
                    revision.lifecycle_status.value,
                    revision.semantic_hash,
                    revision.published_at,
                    _json(revision.content),
                    revision.revision_id,
                ),
            )

    def list_scenario_revisions(self, scenario_id: str) -> tuple[ScenarioRevisionRecord, ...]:
        with _redacted("list scenario revisions"), self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM catalog_scenario_revision WHERE scenario_id = ?"
                " ORDER BY revision_no",
                (scenario_id,),
            ).fetchall()
        return tuple(self._scenario_revision(row) for row in rows)

    # ------------------------------------------------------------------ snapshots and runs

    def add_snapshot(self, snapshot: SnapshotRecord) -> None:
        with _redacted("add snapshot"), self._connection() as connection:
            connection.execute(
                "INSERT INTO catalog_snapshot (snapshot_id, scenario_revision_id, schema_version,"
                " canonicalization_revision, canonical_bytes, content_sha256, validation_status,"
                " validation_code, content_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot.snapshot_id,
                    snapshot.scenario_revision_id,
                    snapshot.schema_version,
                    snapshot.canonicalization_revision,
                    snapshot.canonical_bytes,
                    snapshot.content_sha256,
                    snapshot.validation_status,
                    snapshot.validation_code,
                    _json(snapshot.content),
                ),
            )

    def get_snapshot(self, snapshot_id: str) -> SnapshotRecord | None:
        with _redacted("get snapshot"), self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM catalog_snapshot WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone()
        if row is None:
            return None
        return SnapshotRecord(
            snapshot_id=str(row["snapshot_id"]),
            scenario_revision_id=str(row["scenario_revision_id"]),
            schema_version=str(row["schema_version"]),
            canonicalization_revision=str(row["canonicalization_revision"]),
            canonical_bytes=bytes(row["canonical_bytes"]),
            content_sha256=str(row["content_sha256"]),
            validation_status=str(row["validation_status"]),
            validation_code=row["validation_code"],
            content=_load(row["content_json"]),
        )

    def record_run(self, scenario_id: str, run_id: str) -> None:
        with _redacted("record run"), self._connection() as connection:
            connection.execute(
                "INSERT INTO catalog_scenario_run (scenario_id, run_id) VALUES (?, ?)",
                (scenario_id, run_id),
            )

    def list_runs_for_scenario(self, scenario_id: str) -> tuple[str, ...]:
        with _redacted("list runs for scenario"), self._connection() as connection:
            rows = connection.execute(
                "SELECT run_id FROM catalog_scenario_run WHERE scenario_id = ? ORDER BY seq",
                (scenario_id,),
            ).fetchall()
        return tuple(str(row["run_id"]) for row in rows)

    # ------------------------------------------------------------------ row -> record

    @staticmethod
    def _profile_head(row: sqlite3.Row) -> ProfileHead:
        return ProfileHead(
            profile_id=str(row["profile_id"]),
            stable_key=str(row["stable_key"]),
            kind=ProfileKind(str(row["kind"])),
            name=str(row["name"]),
            description=row["description"],
            is_preset=bool(row["is_preset"]),
            current_revision_id=row["current_revision_id"],
            archived=bool(row["archived"]),
        )

    @staticmethod
    def _profile_revision(row: sqlite3.Row) -> ProfileRevisionRecord:
        return ProfileRevisionRecord(
            revision_id=str(row["revision_id"]),
            profile_id=str(row["profile_id"]),
            profile_kind=ProfileKind(str(row["profile_kind"])),
            revision_no=int(row["revision_no"]),
            lifecycle_status=RevisionStatus(str(row["lifecycle_status"])),
            schema_version=str(row["schema_version"]),
            label=str(row["label"]),
            change_note=row["change_note"],
            based_on_revision_id=row["based_on_revision_id"],
            payload=_load(row["payload_json"]),
            semantic_hash=row["semantic_hash"],
            published_at=row["published_at"],
        )

    @staticmethod
    def _scenario_head(row: sqlite3.Row) -> ScenarioHead:
        return ScenarioHead(
            scenario_id=str(row["scenario_id"]),
            stable_key=str(row["stable_key"]),
            name=str(row["name"]),
            description=row["description"],
            is_preset=bool(row["is_preset"]),
            current_revision_id=row["current_revision_id"],
            archived=bool(row["archived"]),
        )

    @staticmethod
    def _scenario_revision(row: sqlite3.Row) -> ScenarioRevisionRecord:
        return ScenarioRevisionRecord(
            revision_id=str(row["revision_id"]),
            scenario_id=str(row["scenario_id"]),
            revision_no=int(row["revision_no"]),
            lifecycle_status=RevisionStatus(str(row["lifecycle_status"])),
            schema_version=str(row["schema_version"]),
            based_on_revision_id=row["based_on_revision_id"],
            content=_load(row["content_json"]),
            semantic_hash=row["semantic_hash"],
            published_at=row["published_at"],
        )
