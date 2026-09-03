"""Test-wide isolation.

The default persistence tier is SQLite at the per-user data directory. A test run must never
touch that file, so the environment is redirected to a throwaway directory *before* any test
module — and therefore before `interfaces.api.app`, which builds its application at import time —
is imported. `conftest.py` is imported first by pytest, which is why this happens at module level
rather than in a fixture.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

_SANDBOX = Path(tempfile.mkdtemp(prefix="passbudget-tests-"))
os.environ["PASSBUDGET_DATA_DIR"] = str(_SANDBOX)
os.environ.pop("PASSBUDGET_SQLITE_PATH", None)
os.environ.pop("PASSBUDGET_PERSISTENCE", None)
# A stray PASSBUDGET_DATABASE_URL would silently move the default suite onto a server.
# PostgreSQL cases read PASSBUDGET_TEST_DATABASE_URL instead and are marked `postgres`.
os.environ.pop("PASSBUDGET_DATABASE_URL", None)

from semantix_passbudget.domain.models import ScenarioSnapshot  # noqa: E402
from semantix_passbudget.interfaces.dto import load_fixture  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _sandbox_data_dir() -> Iterator[Path]:
    yield _SANDBOX
    shutil.rmtree(_SANDBOX, ignore_errors=True)


@pytest.fixture
def fixture_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "src"
        / "semantix_passbudget"
        / "fixtures"
        / "PB-GOLDEN-CORE-01.json"
    )


@pytest.fixture
def golden_snapshot(fixture_path: Path) -> ScenarioSnapshot:
    return load_fixture(fixture_path).to_domain()


@pytest.fixture
def sqlite_path(tmp_path: Path) -> Path:
    """A throwaway local database file for one test."""
    return tmp_path / "passbudget-test.sqlite3"
