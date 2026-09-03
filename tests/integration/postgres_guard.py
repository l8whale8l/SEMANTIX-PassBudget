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
