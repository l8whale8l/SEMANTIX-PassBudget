"""Keep file references and packaging honest.

Moving DDL between directories is exactly the kind of change that leaves a dead link in a document
or an unshipped file in a wheel. These checks fail instead of letting that happen quietly.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
#: Any `db/...sql` path mentioned anywhere in the repository must exist.
DDL_REFERENCE = re.compile(r"db/(?:[A-Za-z0-9_./-]*?)\.sql")
SEARCHED = ("*.md", "*.py", "*.sql", "*.toml", "*.yml", "*.yaml")
SKIPPED_DIRS = {".venv", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", "build", "dist"}
#: Frozen baseline documents keep their original wording and carry an appended relocation note
#: instead. The note is what a reader follows, so a stale path inside their body is expected.
RELOCATION_NOTE = "경로 안내 (2026-09-03 추가)"


def _searchable_files() -> list[Path]:
    found: list[Path] = []
    for pattern in SEARCHED:
        for path in ROOT.rglob(pattern):
            if any(part in SKIPPED_DIRS for part in path.relative_to(ROOT).parts):
                continue
            found.append(path)
    return sorted(found)


def test_every_referenced_ddl_path_exists() -> None:
    missing: list[str] = []
    for path in _searchable_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):  # pragma: no cover - binary or unreadable file
            continue
        if path.name == Path(__file__).name or RELOCATION_NOTE in text:
            continue
        for reference in set(DDL_REFERENCE.findall(text)):
            if not (ROOT / reference).is_file():
                missing.append(f"{path.relative_to(ROOT)} -> {reference}")
    assert not missing, "dead DDL references:\n" + "\n".join(sorted(missing))


def test_ddl_lives_under_one_directory_per_engine() -> None:
    assert sorted(item.name for item in (ROOT / "db").iterdir()) == ["postgresql", "sqlite"]
    assert (ROOT / "db" / "postgresql" / "schema_v0_1.sql").is_file()
    assert (ROOT / "db" / "sqlite" / "schema_v1.sql").is_file()
    # No stray DDL directly under db/.
    assert not list((ROOT / "db").glob("*.sql"))


def test_the_sqlite_ddl_is_declared_for_the_wheel() -> None:
    """`pip install` must be enough to open a local database, so the DDL has to ship."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    include = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert include["db/sqlite"] == "semantix_passbudget/_ddl/sqlite"


@pytest.mark.parametrize(
    "document",
    ["README.md", "README_EN.md"],
)
def test_relative_document_links_resolve(document: str) -> None:
    text = (ROOT / document).read_text(encoding="utf-8")
    base = (ROOT / document).parent
    broken: list[str] = []
    for target in re.findall(r"\]\((?!https?:)([^)#]+)\)", text):
        if not (base / target).exists():
            broken.append(target)
    assert not broken, f"{document} has broken links: {broken}"
