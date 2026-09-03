"""Inward-dependency rules for the deterministic core.

The domain core may not reach for a framework, a database, the filesystem, the environment, or the
system clock. A calculation that can read the wall clock is not reproducible, and a core that can
import an adapter is not a core.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "semantix_passbudget"
DOMAIN = SRC / "domain"

FORBIDDEN_MODULES = {
    "fastapi",
    "starlette",
    "pydantic",
    "sqlalchemy",
    "alembic",
    "psycopg",
    "os",
    "pathlib",
    "socket",
    "requests",
    "httpx",
    "random",
    "secrets",
}
FORBIDDEN_CALLS = {"now", "utcnow", "today", "time", "monotonic", "perf_counter", "uuid4"}


def _modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


@pytest.mark.parametrize("path", sorted(DOMAIN.glob("*.py")), ids=lambda path: path.name)
def test_domain_module_imports_nothing_from_the_outside(path: Path) -> None:
    forbidden = _modules(path) & FORBIDDEN_MODULES
    assert not forbidden, f"{path.name} imports {sorted(forbidden)}"
    assert "semantix_passbudget" not in path.read_text(encoding="utf-8"), (
        f"{path.name} uses an absolute package import; the core stays relative and inward"
    )


@pytest.mark.parametrize("path", sorted(DOMAIN.glob("*.py")), ids=lambda path: path.name)
def test_domain_module_never_reads_the_system_clock_or_randomness(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    } | {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    forbidden = calls & FORBIDDEN_CALLS
    assert not forbidden, f"{path.name} calls {sorted(forbidden)}"


def test_ports_do_not_import_adapters() -> None:
    for path in sorted((SRC / "ports").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith(("import ", "from ")) and "adapters" in line:
                assert "TYPE_CHECKING" in text, f"{path.name} imports an adapter at runtime"


def test_application_layer_does_not_import_the_http_framework() -> None:
    for path in sorted((SRC / "application").glob("*.py")):
        forbidden = _modules(path) & {"fastapi", "starlette"}
        assert not forbidden, f"{path.name} imports {sorted(forbidden)}"


def test_only_the_composition_root_reads_the_environment() -> None:
    readers = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if "os" in _modules(path) and "getenv" in path.read_text(encoding="utf-8")
    ]
    assert readers == ["application/composition.py"], readers
