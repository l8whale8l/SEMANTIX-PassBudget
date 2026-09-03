"""Keep `docs/specs/P0_ACCEPTANCE_MATRIX.md` honest.

A status table drifts the moment a test is renamed. These checks make the document executable:
every acceptance criterion must appear, every named test must actually exist, and a criterion may
only claim PASS if the tests it names are collectible.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "specs" / "P0_ACCEPTANCE_MATRIX.md"
VALID_STATUSES = {"PASS", "PARTIAL", "BLOCKED", "MISSING"}
ROW = re.compile(r"^\| (AC-P0-\d\d) \| (.+?) \| (\w+) \| (.*?) \| (.*?) \|$")
NODE = re.compile(r"`(tests/[\w/]+\.py::\w+)`")


def _rows() -> dict[str, tuple[str, list[str], str]]:
    parsed: dict[str, tuple[str, list[str], str]] = {}
    for line in MATRIX.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line.strip())
        if match is None:
            continue
        criterion, _, status, tests, note = match.groups()
        parsed[criterion] = (status, NODE.findall(tests), note)
    return parsed


def _collected_node_ids() -> set[str]:
    ids: set[str] = set()
    for path in sorted(ROOT.joinpath("tests").rglob("test_*.py")):
        module = path.relative_to(ROOT).as_posix()
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("def test_"):
                ids.add(f"{module}::{line[4:].split('(')[0]}")
    return ids


def test_every_acceptance_criterion_is_listed() -> None:
    rows = _rows()
    expected = {f"AC-P0-{index:02d}" for index in range(1, 26)}
    assert set(rows) == expected, f"missing or extra rows: {expected ^ set(rows)}"


def test_every_status_is_a_declared_status() -> None:
    for criterion, (status, _, _) in _rows().items():
        assert status in VALID_STATUSES, f"{criterion} has status {status!r}"


@pytest.mark.parametrize("criterion", [f"AC-P0-{index:02d}" for index in range(1, 26)])
def test_named_tests_exist(criterion: str) -> None:
    status, nodes, note = _rows()[criterion]
    if status in {"BLOCKED", "MISSING"}:
        assert note.strip(), f"{criterion} is {status} and must explain why"
        return
    assert nodes, f"{criterion} claims {status} but names no test"
    collected = _collected_node_ids()
    missing = [node for node in nodes if node not in collected]
    assert not missing, f"{criterion} names tests that do not exist: {missing}"


def test_partial_rows_explain_what_is_missing() -> None:
    for criterion, (status, _, note) in _rows().items():
        if status == "PARTIAL":
            assert len(note.strip()) > 40, f"{criterion} is PARTIAL with no explanation"
