"""Composition root and persistence-selection policy.

This is the only module that reads the environment. The domain core, the application services and
the interfaces receive their collaborators through constructor injection.

Selection policy, highest precedence first:

1. `PASSBUDGET_PERSISTENCE` — an explicit tier: `memory`, `sqlite` or `postgresql`.
2. `PASSBUDGET_DATABASE_URL` — a PostgreSQL URL. Setting it is the only way to reach the
   server tier, so a deployment can never be joined by accident.
3. `PASSBUDGET_SQLITE_PATH` — an explicit local database file.
4. Otherwise the caller's default: the pure-calculation CLI runs in memory, the API and any
   other persistent entry point use SQLite at the platform data directory.

There is no implicit PostgreSQL. A missing or empty `PASSBUDGET_DATABASE_URL` never silently
falls back to a server, and a URL is never logged, echoed or included in an error payload.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from semantix_passbudget.adapters.memory_catalog import InMemoryCatalogRepository
from semantix_passbudget.adapters.memory_repository import InMemoryRunRepository
from semantix_passbudget.adapters.orbit.provider import OrbitContactProvider
from semantix_passbudget.adapters.synthetic_contact import SyntheticContactProvider
from semantix_passbudget.application.catalog import CatalogService
from semantix_passbudget.application.service import RunScenarioService
from semantix_passbudget.interfaces.dto import PUBLIC_FIXTURE_IDS, load_fixture_source
from semantix_passbudget.ports.catalog_repository import CatalogRepository
from semantix_passbudget.ports.run_repository import RunRepository

#: Explicit tier override. Highest precedence.
PERSISTENCE_ENV = "PASSBUDGET_PERSISTENCE"
#: PostgreSQL URL. Present and non-empty is the *only* way to select the server tier.
DATABASE_URL_ENV = "PASSBUDGET_DATABASE_URL"
#: Local SQLite database file.
SQLITE_PATH_ENV = "PASSBUDGET_SQLITE_PATH"
#: Base directory override, mainly for tests and packaged distributions.
DATA_DIR_ENV = "PASSBUDGET_DATA_DIR"

Persistence = Literal["memory", "sqlite", "postgresql"]
VALID_TIERS: tuple[Persistence, ...] = ("memory", "sqlite", "postgresql")

DATABASE_FILENAME = "passbudget.sqlite3"


class ConfigurationError(RuntimeError):
    """The persistence configuration is contradictory or unusable.

    The message names the environment variable, never its value, because that value may be a
    connection string.
    """


def default_data_dir() -> Path:
    """Per-user application data directory. Never the repository or the working directory."""
    override = os.getenv(DATA_DIR_ENV)
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
        if base:
            return Path(base) / "SEMANTIX" / "PassBudget"
        return Path.home() / "AppData" / "Local" / "SEMANTIX" / "PassBudget"
    xdg = os.getenv("XDG_DATA_HOME")
    root = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return root / "semantix-passbudget"


def default_database_path() -> Path:
    return default_data_dir() / DATABASE_FILENAME


def resolve_persistence(*, default: Persistence) -> Persistence:
    """Decide the tier without constructing anything, so callers can report it."""
    requested = (os.getenv(PERSISTENCE_ENV) or "").strip().lower()
    if requested:
        if requested not in VALID_TIERS:
            raise ConfigurationError(f"{PERSISTENCE_ENV} must be one of {', '.join(VALID_TIERS)}.")
        tier: Persistence = requested
        if tier == "postgresql" and not (os.getenv(DATABASE_URL_ENV) or "").strip():
            raise ConfigurationError(
                f"{PERSISTENCE_ENV}=postgresql also requires {DATABASE_URL_ENV}."
            )
        return tier
    if (os.getenv(DATABASE_URL_ENV) or "").strip():
        return "postgresql"
    if (os.getenv(SQLITE_PATH_ENV) or "").strip():
        return "sqlite"
    return default


def build_run_repository(*, default: Persistence) -> tuple[RunRepository, str]:
    tier = resolve_persistence(default=default)
    if tier == "memory":
        return InMemoryRunRepository(), "memory"
    if tier == "sqlite":
        from semantix_passbudget.adapters.sqlite.repository import SqliteRunRepository

        configured = (os.getenv(SQLITE_PATH_ENV) or "").strip()
        path = Path(configured) if configured else default_database_path()
        return SqliteRunRepository(path), "sqlite"

    from sqlalchemy import create_engine

    from semantix_passbudget.adapters.postgres.repository import PostgresRunRepository

    url = (os.getenv(DATABASE_URL_ENV) or "").strip()
    if not url:  # pragma: no cover - resolve_persistence already rejects this
        raise ConfigurationError(f"{DATABASE_URL_ENV} is required for the postgresql tier.")
    # `hide_parameters` keeps bound values out of SQLAlchemy error text; `echo=False` keeps the
    # statement log off entirely so no snapshot content or credential is ever written to stdout.
    engine = create_engine(url, echo=False, hide_parameters=True, future=True)
    return PostgresRunRepository(engine), "postgresql"


def describe_persistence(*, default: Persistence = "sqlite") -> dict[str, object]:
    """Report the tier the current environment resolves to, without opening anything.

    A PostgreSQL URL is never echoed: it can carry a credential and a host address.
    """
    tier = resolve_persistence(default=default)
    location: str | None
    if tier == "sqlite":
        configured = (os.getenv(SQLITE_PATH_ENV) or "").strip()
        location = configured or str(default_database_path())
    elif tier == "postgresql":
        location = f"configured through {DATABASE_URL_ENV}"
    else:
        location = None
    return {
        "calculation_default": "memory (no database)",
        "persistent_tier": tier,
        "database_location": location,
        "environment_precedence": [
            PERSISTENCE_ENV,
            DATABASE_URL_ENV,
            SQLITE_PATH_ENV,
            DATA_DIR_ENV,
        ],
        "notice": (
            "SQLite is a single-writer local store. Use the PostgreSQL tier for a shared or "
            "multi-user deployment."
        ),
    }


@dataclass(frozen=True, slots=True)
class Application:
    runs: RunScenarioService
    catalog: CatalogService
    catalog_repository: CatalogRepository
    persistence: str
    #: Location of the local database when the SQLite tier is active, else None. Shown by
    #: `passbudget where` so an operator can back it up or delete it deliberately.
    database_path: str | None = None


def build_application(
    *,
    seed_presets: bool = True,
    default_persistence: Persistence = "sqlite",
) -> Application:
    repository, persistence = build_run_repository(default=default_persistence)
    database_path = getattr(repository, "path", None)
    # The catalog follows the run tier. On SQLite it persists to the *same* file so scenarios,
    # revisions and snapshots survive a restart (both open one local database). Every other tier
    # keeps the volatile in-memory catalog — the optional PostgreSQL catalog is out of this scope.
    catalog_repository: CatalogRepository
    if persistence == "sqlite" and database_path is not None:
        from semantix_passbudget.adapters.sqlite.catalog_repository import SqliteCatalogRepository

        catalog_repository = SqliteCatalogRepository(database_path)
    else:
        catalog_repository = InMemoryCatalogRepository()
    catalog = CatalogService(catalog_repository)
    runs = RunScenarioService(
        SyntheticContactProvider(), repository, orbit_provider=OrbitContactProvider()
    )
    if seed_presets:
        published_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        for fixture_id in PUBLIC_FIXTURE_IDS:
            content = load_fixture_source(fixture_id).model_dump(mode="json")
            catalog.seed_scenario_preset(content, published_at=published_at)
    return Application(
        runs=runs,
        catalog=catalog,
        catalog_repository=catalog_repository,
        persistence=persistence,
        database_path=str(database_path) if database_path else None,
    )
