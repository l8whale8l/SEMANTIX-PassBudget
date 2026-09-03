"""The persistence-selection policy, tested where it lives: the composition root.

The rule that matters most is negative — nothing may reach PostgreSQL implicitly. Everything
else follows from a documented precedence order.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from semantix_passbudget.application import composition
from semantix_passbudget.application.composition import (
    DATA_DIR_ENV,
    DATABASE_URL_ENV,
    PERSISTENCE_ENV,
    SQLITE_PATH_ENV,
    ConfigurationError,
    build_run_repository,
    default_database_path,
    describe_persistence,
    resolve_persistence,
)

ALL_ENV = (PERSISTENCE_ENV, DATABASE_URL_ENV, SQLITE_PATH_ENV, DATA_DIR_ENV)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ALL_ENV:
        monkeypatch.delenv(name, raising=False)


def test_calculation_default_is_memory_and_never_touches_a_database() -> None:
    assert resolve_persistence(default="memory") == "memory"
    repository, tier = build_run_repository(default="memory")
    assert tier == "memory"
    assert not hasattr(repository, "path")


def test_persistent_default_is_sqlite() -> None:
    assert resolve_persistence(default="sqlite") == "sqlite"


def test_postgresql_is_never_selected_implicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unset, empty or whitespace-only URL must not reach a server."""
    for value in (None, "", "   "):
        if value is None:
            monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
        else:
            monkeypatch.setenv(DATABASE_URL_ENV, value)
        assert resolve_persistence(default="sqlite") == "sqlite"
        assert resolve_persistence(default="memory") == "memory"


def test_a_database_url_selects_the_server_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        DATABASE_URL_ENV,
        "postgresql+psycopg://passbudget_test:test_only_not_a_secret@127.0.0.1:5432/pb",
    )
    assert resolve_persistence(default="memory") == "postgresql"


def test_explicit_tier_wins_over_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        DATABASE_URL_ENV,
        "postgresql+psycopg://passbudget_test:test_only_not_a_secret@127.0.0.1:5432/pb",
    )
    monkeypatch.setenv(PERSISTENCE_ENV, "memory")
    assert resolve_persistence(default="sqlite") == "memory"


def test_sqlite_path_selects_the_local_tier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "nested" / "local.sqlite3"
    monkeypatch.setenv(SQLITE_PATH_ENV, str(target))
    assert resolve_persistence(default="memory") == "sqlite"
    repository, tier = build_run_repository(default="memory")
    assert tier == "sqlite"
    assert Path(repository.path) == target  # type: ignore[attr-defined]
    assert target.exists(), "the adapter creates its parent directory"


def test_an_unknown_tier_name_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PERSISTENCE_ENV, "mysql")
    with pytest.raises(ConfigurationError) as caught:
        resolve_persistence(default="sqlite")
    assert PERSISTENCE_ENV in str(caught.value)


def test_postgresql_tier_without_a_url_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PERSISTENCE_ENV, "postgresql")
    with pytest.raises(ConfigurationError):
        resolve_persistence(default="sqlite")


def test_the_default_database_lives_in_a_user_data_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))
    assert default_database_path() == tmp_path / composition.DATABASE_FILENAME


def test_the_default_database_is_not_in_the_repository_or_the_working_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATA_DIR_ENV, raising=False)
    path = default_database_path().resolve()
    repository_root = Path(__file__).resolve().parents[2]
    assert repository_root not in path.parents
    assert Path.cwd() not in path.parents


def test_describe_persistence_never_echoes_the_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = (
        "postgresql+psycopg://passbudget_ops:test_only_not_a_secret@db.internal:5432/passbudget"
    )
    monkeypatch.setenv(DATABASE_URL_ENV, secret)
    described = describe_persistence()
    rendered = repr(described)
    assert described["persistent_tier"] == "postgresql"
    assert "test_only_not_a_secret" not in rendered
    assert "db.internal" not in rendered
    assert DATABASE_URL_ENV in str(described["database_location"])


def test_describe_persistence_reports_the_local_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))
    described = describe_persistence()
    assert described["persistent_tier"] == "sqlite"
    assert described["database_location"] == str(tmp_path / composition.DATABASE_FILENAME)
    assert described["calculation_default"] == "memory (no database)"
    assert "single-writer" in str(described["notice"])
