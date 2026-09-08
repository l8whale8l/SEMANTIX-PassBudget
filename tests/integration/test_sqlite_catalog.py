"""The SQLite catalog persists scenarios/revisions/snapshots across a restart.

A "restart" here is a brand-new `build_application` on the same database file — exactly what the
server does when its process is stopped and started again. The in-memory catalog would lose
everything; the SQLite catalog must not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from semantix_passbudget.application.composition import build_application
from semantix_passbudget.domain.enums import ProfileKind
from semantix_passbudget.interfaces.dto import load_public_fixture

PUBLISHED_AT = "2026-09-05T00:00:00.000000Z"


@pytest.fixture
def sqlite_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    database = tmp_path / "catalog.sqlite3"
    monkeypatch.setenv("PASSBUDGET_PERSISTENCE", "sqlite")
    monkeypatch.setenv("PASSBUDGET_SQLITE_PATH", str(database))
    monkeypatch.delenv("PASSBUDGET_DATABASE_URL", raising=False)
    return database


def _orb_content() -> dict:
    return load_public_fixture("PB-GOLDEN-ORB-01").model_dump(mode="json")


def test_a_saved_scenario_survives_a_restart(sqlite_env: Path) -> None:
    app1 = build_application(default_persistence="sqlite")
    assert app1.persistence == "sqlite"
    head, draft = app1.catalog.create_scenario(
        stable_key="SC-RESTART-01", name="restart me", content=_orb_content()
    )
    published = app1.catalog.publish_scenario_revision(draft.revision_id, published_at=PUBLISHED_AT)
    snapshot = app1.catalog.create_snapshot(published.revision_id)

    # Full restart: a new application object on the same file, with no shared memory.
    app2 = build_application(default_persistence="sqlite")
    restored_head, revisions, _ = app2.catalog.get_scenario(head.scenario_id)
    assert restored_head.name == "restart me"
    assert restored_head.current_revision_id == published.revision_id
    assert len(revisions) == 1

    restored_revision = app2.catalog.get_scenario_revision_or_none(published.revision_id)
    assert restored_revision is not None
    assert restored_revision.lifecycle_status.value == "PUBLISHED"
    assert restored_revision.content["fixture_id"] == "PB-GOLDEN-ORB-01"

    restored_snapshot = app2.catalog.get_snapshot(snapshot.snapshot_id)
    assert restored_snapshot is not None
    assert restored_snapshot.content_sha256 == snapshot.content_sha256


def test_a_new_revision_persists_and_leaves_the_published_one_immutable(sqlite_env: Path) -> None:
    app1 = build_application(default_persistence="sqlite")
    head, draft = app1.catalog.create_scenario(
        stable_key="SC-RESTART-02", name="revisions", content=_orb_content()
    )
    first = app1.catalog.publish_scenario_revision(draft.revision_id, published_at=PUBLISHED_AT)
    edited = _orb_content()
    edited["decision_question"] = "Edited question for a new revision."
    second_draft = app1.catalog.create_scenario_revision(head.scenario_id, content=edited)
    second = app1.catalog.publish_scenario_revision(
        second_draft.revision_id, published_at=PUBLISHED_AT
    )

    app2 = build_application(default_persistence="sqlite")
    _, revisions, _ = app2.catalog.get_scenario(head.scenario_id)
    assert len(revisions) == 2
    # The first published revision is unchanged; the current pointer moved to the second.
    unchanged = app2.catalog.get_scenario_revision_or_none(first.revision_id)
    assert unchanged is not None
    assert unchanged.content["decision_question"] != "Edited question for a new revision."
    restored_head, _, _ = app2.catalog.get_scenario(head.scenario_id)
    assert restored_head.current_revision_id == second.revision_id


def test_recorded_runs_survive_a_restart(sqlite_env: Path) -> None:
    app1 = build_application(default_persistence="sqlite")
    head, _ = app1.catalog.create_scenario(
        stable_key="SC-RESTART-03", name="runs", content=_orb_content()
    )
    app1.catalog_repository.record_run(head.scenario_id, "run-a")
    app1.catalog_repository.record_run(head.scenario_id, "run-b")

    app2 = build_application(default_persistence="sqlite")
    assert app2.catalog_repository.list_runs_for_scenario(head.scenario_id) == ("run-a", "run-b")


def test_a_saved_satellite_preset_profile_survives_a_restart(sqlite_env: Path) -> None:
    """A satellite preset stored as a SPACECRAFT profile (opaque payload = name + orbit) is
    restored across a real restart on the SQLite tier, payload intact."""
    payload = {
        "schema": "passbudget-satellite-preset-1",
        "name": "국민대 관측위성 A (가정)",
        "provenance": "연습용 가정 궤도 · 실측 아님",
        "isAssumption": True,
        "orbit": {
            "kind": "TWO_BODY_V1",
            "two_body": {
                "epoch": "2026-09-03T00:00:00Z",
                "semi_major_axis_mm": 7_078_137_000,
                "eccentricity_ppb": 0,
                "inclination_udeg": 98_000_000,
                "raan_udeg": 90_000_000,
                "argument_of_perigee_udeg": 0,
                "true_anomaly_udeg": 0,
                "mu_m3_per_s2": 398_600_441_500_000,
            },
        },
    }
    app1 = build_application(default_persistence="sqlite")
    head = app1.catalog.create_profile(
        stable_key="SAT-RESTART-01",
        kind=ProfileKind.SPACECRAFT,
        name=payload["name"],
        is_preset=True,
    )
    draft = app1.catalog.create_profile_revision(head.profile_id, payload=payload, label="v1")
    published = app1.catalog.publish_profile_revision(draft.revision_id, published_at=PUBLISHED_AT)

    # Full restart on the same file.
    app2 = build_application(default_persistence="sqlite")
    restored_head, _revisions = app2.catalog.get_profile(head.profile_id)
    assert restored_head.name == payload["name"]
    assert restored_head.current_revision_id == published.revision_id
    assert restored_head.is_preset is True

    restored = app2.catalog.get_profile_revision_or_none(published.revision_id)
    assert restored is not None
    assert restored.lifecycle_status.value == "PUBLISHED"
    assert restored.payload == payload  # opaque payload restored byte-for-byte


def test_preset_seeding_is_idempotent_across_restart(sqlite_env: Path) -> None:
    app1 = build_application(default_persistence="sqlite")
    first = {s.stable_key for s in app1.catalog_repository.list_scenarios(is_preset=True)}
    assert "PB-GOLDEN-ORB-01" in first

    # Re-seeding on restart must not raise DUPLICATE_STABLE_KEY nor duplicate rows.
    app2 = build_application(default_persistence="sqlite")
    second = app2.catalog_repository.list_scenarios(is_preset=True)
    keys = [s.stable_key for s in second]
    assert len(keys) == len(set(keys))
    assert set(keys) == first
