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
    # The orbit engine. ADR-0004 keeps every propagator behind the ContactProvider port, so the
    # domain must never see an orbit library -- exactly as it never sees SQLAlchemy.
    "sgp4",
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


def test_the_orbit_engine_stays_behind_its_adapter() -> None:
    """ADR-0004: no layer above `adapters/orbit` may import the propagator.

    The orbit adapter is the only place allowed to touch `sgp4`. If a future change imports it
    from the domain, the application layer or an interface, the engine stops being replaceable
    and the float-precision boundary in ADR-0001's numerical contract stops being enforceable.
    """
    orbit_adapter = SRC / "adapters" / "orbit"
    offenders = []
    for path in SRC.rglob("*.py"):
        if orbit_adapter in path.parents:
            continue
        if "sgp4" in _modules(path):
            offenders.append(path.relative_to(SRC).as_posix())
    assert not offenders, f"orbit engine imported outside its adapter: {offenders}"


def test_the_synthetic_provider_is_untouched_by_the_orbit_work() -> None:
    """The synthetic provider stays a separate provider, not a mode of the orbit one.

    ADR-0004 forbids merging or wrapping them: a shared code path is how a synthetic result
    would eventually get relabelled as an orbit result.
    """
    synthetic = (SRC / "adapters" / "synthetic_contact.py").read_text(encoding="utf-8")
    assert "sgp4" not in synthetic
    assert "orbit" not in synthetic.lower().replace("orbit-accuracy", "")
