"""Safety guard for the destructive PostgreSQL integration tests.

Those tests run `DROP SCHEMA passbudget CASCADE` and `DROP TABLE public.alembic_version`. Pointing
`PASSBUDGET_TEST_DATABASE_URL` at a real deployment would destroy it. This module refuses any URL
that does not look unmistakably disposable, and it refuses the runtime variable outright so a
developer cannot reach production by exporting one variable too many.

The URL itself is never included in an error message: the failure names the rule, not the value.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

import pytest

TEST_URL_ENV = "PASSBUDGET_TEST_DATABASE_URL"
RUNTIME_URL_ENV = "PASSBUDGET_DATABASE_URL"

#: Fixtures the accepted PostgreSQL schema can represent.
#:
#: `PB-GOLDEN-ACK-01` is deliberately excluded. It sets `release_trigger = ACKED`, which the
#: accepted v0.1 enum does not contain and which `scenario_storage_ck` would reject even if it
#: did. That is a documented, open specification conflict (`CONFLICT-STORE-01`), not a defect to
#: work around: the domain supports ACKED for `TEST_SYNTHETIC` events, the PostgreSQL tier cannot
#: store it, and `test_postgres_persistence.py` asserts that the refusal is explicit.
POSTGRES_UNSUPPORTED_FIXTURES = ("PB-GOLDEN-ACK-01",)


def postgres_capable_fixtures() -> tuple[str, ...]:
    from semantix_passbudget.interfaces.dto import PUBLIC_FIXTURE_IDS

    return tuple(
        fixture for fixture in PUBLIC_FIXTURE_IDS if fixture not in POSTGRES_UNSUPPORTED_FIXTURES
    )


#: A disposable database announces itself in its name.
DISPOSABLE_NAME = re.compile(r"(?i)(^|[_-])(test|tests|ci|tmp|temp|scratch|disposable)([_-]|$)")
#: Only a loopback or an obvious container/CI host is accepted.
LOCAL_HOSTS = frozenset(
    {"", "localhost", "127.0.0.1", "::1", "postgres", "db", "postgresql", "host.docker.internal"}
)


class UnsafeTestDatabaseError(RuntimeError):
    """The configured test database URL does not look disposable."""


def _reject(reason: str) -> UnsafeTestDatabaseError:
    return UnsafeTestDatabaseError(
        f"{TEST_URL_ENV} is refused: {reason}. These tests drop the passbudget schema and the "
        "Alembic version table, so they only accept a disposable database — a loopback or "
        "container host and a database name containing test, ci, tmp or scratch."
    )


def require_disposable_url() -> str:
    """Return the test URL, or skip. Raise rather than run against anything that could be real."""
    if (os.getenv(RUNTIME_URL_ENV) or "").strip():
        raise _reject(
            f"{RUNTIME_URL_ENV} is set. The runtime database is never a test target; unset it "
            f"and configure {TEST_URL_ENV} instead"
        )
    url = (os.getenv(TEST_URL_ENV) or "").strip()
    if not url:
        pytest.skip(f"{TEST_URL_ENV} is not configured")
    parts = urlsplit(url)
    if not parts.scheme.startswith("postgres"):
        raise _reject("the scheme is not PostgreSQL")
    host = (parts.hostname or "").lower()
    if host not in LOCAL_HOSTS:
        raise _reject("the host is neither loopback nor a known container/CI service name")
    name = parts.path.lstrip("/")
    if not name:
        raise _reject("no database name is present")
    if not DISPOSABLE_NAME.search(name):
        raise _reject("the database name does not mark it as disposable")
    return url
