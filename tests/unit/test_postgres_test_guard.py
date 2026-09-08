"""The PostgreSQL integration tests are destructive; the guard is what makes them safe."""

from __future__ import annotations

import pytest

from tests.integration.postgres_guard import (
    RUNTIME_URL_ENV,
    TEST_URL_ENV,
    UnsafeTestDatabaseError,
    require_disposable_url,
)

SAFE = "postgresql+psycopg://passbudget_test:test_only_not_a_secret@127.0.0.1:5432/passbudget_test"


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TEST_URL_ENV, raising=False)
    monkeypatch.delenv(RUNTIME_URL_ENV, raising=False)


def test_a_disposable_local_url_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TEST_URL_ENV, SAFE)
    assert require_disposable_url() == SAFE


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://passbudget_ops:test_only_not_a_secret@db.example.com:5432/passbudget_test",
        "postgresql+psycopg://passbudget_ops:test_only_not_a_secret@10.0.0.7:5432/passbudget_ci",
        "postgresql+psycopg://passbudget_ops:test_only_not_a_secret@127.0.0.1:5432/passbudget",
        "postgresql+psycopg://passbudget_ops:test_only_not_a_secret@127.0.0.1:5432/production",
        "postgresql+psycopg://passbudget_ops:test_only_not_a_secret@127.0.0.1:5432/",
        "mysql://passbudget_ops:test_only_not_a_secret@127.0.0.1:3306/passbudget_test",
    ],
)
def test_anything_that_could_be_real_is_refused(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv(TEST_URL_ENV, url)
    with pytest.raises(UnsafeTestDatabaseError):
        require_disposable_url()


def test_the_runtime_url_is_never_a_test_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(TEST_URL_ENV, SAFE)
    monkeypatch.setenv(
        RUNTIME_URL_ENV,
        "postgresql+psycopg://passbudget_ops:test_only_not_a_secret@127.0.0.1:5432/passbudget",
    )
    with pytest.raises(UnsafeTestDatabaseError):
        require_disposable_url()


def test_the_refusal_never_repeats_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        TEST_URL_ENV, "postgresql+psycopg://passbudget_ops:test_only_not_a_secret@db.internal/prod"
    )
    with pytest.raises(UnsafeTestDatabaseError) as caught:
        require_disposable_url()
    message = str(caught.value)
    assert "test_only_not_a_secret" not in message
    assert "db.internal" not in message


def test_an_absent_url_skips_rather_than_failing(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(BaseException) as caught:
        require_disposable_url()
    assert caught.typename == "Skipped"
