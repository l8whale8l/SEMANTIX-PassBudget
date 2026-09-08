"""No public surface may reveal a connection string, a credential or a host path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.exc import DBAPIError

from semantix_passbudget.adapters.postgres.repository import (
    PersistenceError,
    PostgresRunRepository,
    _redacted,
)
from semantix_passbudget.application.composition import DATABASE_URL_ENV, build_application
from semantix_passbudget.domain.errors import DomainValidationError, ErrorDetail
from semantix_passbudget.interfaces.dto import PUBLIC_FIXTURE_IDS, load_fixture_source

SECRET_URL = "postgresql+psycopg://pb_user:super_secret_pw@10.0.0.7:5432/passbudget"
FORBIDDEN = ("super_secret_pw", "10.0.0.7", "pb_user", "postgresql+psycopg://", "traceback")


def test_driver_error_is_redacted_without_constructing_or_chaining_it() -> None:
    driver_error = DBAPIError("SELECT secret", {"password": "secret"}, RuntimeError("host"))
    with pytest.raises(PersistenceError) as caught, _redacted("test operation"):
        raise driver_error
    assert str(caught.value) == "persistence operation failed: test operation"
    assert caught.value.__cause__ is None


def test_persistence_failure_message_carries_no_connection_detail(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(DATABASE_URL_ENV, SECRET_URL)
    application = build_application(seed_presets=False)
    assert application.persistence == "postgresql"
    run = None
    for fixture_id in PUBLIC_FIXTURE_IDS[:1]:
        run = load_fixture_source(fixture_id)
    assert run is not None
    repository = application.runs.repository
    assert isinstance(repository, PostgresRunRepository)
    with pytest.raises(PersistenceError) as caught:
        repository.add(  # type: ignore[arg-type]
            type(
                "Incomplete",
                (),
                {"snapshot": None, "run_id": "x"},
            )()
        )
    rendered = str(caught.value).lower()
    assert not any(value in rendered for value in FORBIDDEN)


def test_domain_error_payload_has_no_host_path_or_stack() -> None:
    detail = ErrorDetail(
        code="INPUT_FACTOR_CONFLICT",
        message="Fixed rate and final per-contact capacity inputs are mutually exclusive.",
        scope="communication_revision",
        field_paths=("capacity.rate_segments",),
        affected_branches=("capacity",),
    )
    payload = json.dumps(DomainValidationError(detail).detail.as_dict())
    assert "\\\\" not in payload
    assert not any(value in payload.lower() for value in FORBIDDEN)


def test_no_packaged_fixture_contains_a_credential_or_host_address() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "semantix_passbudget" / "fixtures"
    for path in sorted(root.glob("*.json")):
        text = path.read_text(encoding="utf-8").lower()
        assert "password" not in text
        assert "://" not in text
        assert "c:\\" not in text
