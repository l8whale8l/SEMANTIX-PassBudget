"""Row-mapping round trip without a database.

`rows_view(result_rows(result))` is the canonical projection of everything the relational schema
stores. These tests prove the projection is total for the golden results, independent of input
ordering, and stable under a JSON round trip, so the live PostgreSQL test only has to prove that
the same rows survive a real write and read.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from semantix_passbudget.adapters.memory_repository import InMemoryRunRepository
from semantix_passbudget.adapters.synthetic_contact import SyntheticContactProvider
from semantix_passbudget.application.service import RunScenarioService
from semantix_passbudget.interfaces.dto import load_fixture
from semantix_passbudget.ports.persisted_rows import (
    PersistedRows,
    result_rows,
    rows_bytes,
    rows_hash,
    rows_view,
)

FIXTURES = Path(__file__).resolve().parents[2] / "src" / "semantix_passbudget" / "fixtures"


def _run(name: str) -> dict[str, object]:
    snapshot = load_fixture(FIXTURES / f"{name}.json").to_domain()
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    return service.run(snapshot).result


def test_every_result_row_has_a_typed_subtype_row() -> None:
    rows = result_rows(_run("PB-GOLDEN-ACK-01"))
    typed = {
        *(item["stable_key"] for item in rows.geometric),
        *(item["stable_key"] for item in rows.modeled),
        *(item["stable_key"] for item in rows.candidates),
        *(item["stable_key"] for item in rows.scheduled),
        *(item["stable_key"] for item in rows.allocations),
        *(item["stable_key"] for item in rows.events),
        *(item["stable_key"] for item in rows.metrics),
        *(item["stable_key"] for item in rows.annotations),
    }
    assert {item["stable_key"] for item in rows.results} == typed
    assert len({item["stable_key"] for item in rows.results}) == len(rows.results)


def test_lineage_links_resolve_through_stable_keys() -> None:
    rows = result_rows(_run("PB-GOLDEN-QUEUE-01"))
    geometric = {item["stable_key"] for item in rows.geometric}
    modeled = {item["stable_key"] for item in rows.modeled}
    candidates = {item["stable_key"] for item in rows.candidates}
    scheduled = {item["stable_key"] for item in rows.scheduled}
    assert all(item["geometric_stable_key"] in geometric for item in rows.modeled)
    assert all(item["modeled_stable_key"] in modeled for item in rows.candidates)
    assert all(item["candidate_stable_key"] in candidates for item in rows.scheduled)
    assert all(item["scheduled_session_stable_key"] in scheduled for item in rows.allocations)


def test_row_order_never_changes_the_persisted_view() -> None:
    rows = result_rows(_run("PB-GOLDEN-QUEUE-01"))
    shuffled = PersistedRows(
        results=tuple(reversed(rows.results)),
        geometric=tuple(reversed(rows.geometric)),
        modeled=tuple(reversed(rows.modeled)),
        candidates=tuple(reversed(rows.candidates)),
        scheduled=tuple(reversed(rows.scheduled)),
        allocations=tuple(reversed(rows.allocations)),
        events=tuple(reversed(rows.events)),
        metrics=tuple(reversed(rows.metrics)),
        annotations=tuple(reversed(rows.annotations)),
    )
    assert rows_view(rows) == rows_view(shuffled)
    assert rows_hash(rows) == rows_hash(shuffled)


def test_input_permutation_does_not_change_the_persisted_view() -> None:
    snapshot = load_fixture(FIXTURES / "PB-GOLDEN-QUEUE-01.json").to_domain()
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    baseline = service.run(snapshot)
    permuted = service.run(
        replace(
            snapshot,
            stations=tuple(reversed(snapshot.stations)),
            contacts=tuple(reversed(snapshot.contacts)),
            payloads=tuple(reversed(snapshot.payloads)),
        )
    )
    assert rows_hash(result_rows(baseline.result)) == rows_hash(result_rows(permuted.result))


def test_persisted_view_survives_a_json_round_trip() -> None:
    rows = result_rows(_run("PB-GOLDEN-ACK-01"))
    encoded = rows_bytes(rows)
    decoded = json.loads(encoded.decode("utf-8"))
    assert json.loads(rows_bytes(rows).decode("utf-8")) == decoded
    # Byte counts survive as decimal strings, never as binary floats.
    occupancy = [
        row["occupancy_bytes"]
        for row in decoded["run_events"]
        if row["occupancy_bytes"] is not None
    ]
    assert all(isinstance(value, str) for value in occupancy)
    assert "145000000" in occupancy


def test_synthetic_geometric_rows_carry_no_invented_elevation() -> None:
    rows = result_rows(_run("PB-GOLDEN-CORE-01"))
    assert rows.geometric
    for row in rows.geometric:
        assert row["contact_source"] == "SYNTHETIC_INJECTED"
        assert row["maximum_elevation_udeg"] is None
        assert row["maximum_elevation_at"] is None
