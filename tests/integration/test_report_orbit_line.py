"""The plain-text report's orbit-dependency line must reflect the actual computation (FE-GAP-05).

Previously it was hard-coded to NOT_APPLICABLE, which misrepresented an ORBIT_DERIVED run whose
contact windows are computed from the orbit. This is a report-text fix only: no metric, hash or
golden value changes.
"""

from __future__ import annotations

from semantix_passbudget.application.comparison import render_report
from semantix_passbudget.application.composition import build_application
from semantix_passbudget.interfaces.dto import load_public_fixture


def _report(fixture_id: str) -> str:
    app = build_application(default_persistence="memory")
    run = app.runs.run(load_public_fixture(fixture_id).to_domain())
    return render_report(run.result)


def test_orbit_derived_report_shows_computed_orbit_dependency() -> None:
    report = _report("PB-GOLDEN-ORB-01")
    assert "궤도 의존성: COMPUTED" in report
    assert "궤도 의존성: NOT_APPLICABLE" not in report
    assert "TWO_BODY_V1" in report  # the orbit kind is named


def test_synthetic_report_still_shows_not_applicable() -> None:
    report = _report("PB-GOLDEN-CORE-01")
    assert "궤도 의존성: NOT_APPLICABLE" in report
