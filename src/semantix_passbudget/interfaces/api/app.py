from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse

from semantix_passbudget.application.comparison import compare_results, render_report
from semantix_passbudget.application.composition import build_application
from semantix_passbudget.application.daily_budget import daily_budget
from semantix_passbudget.domain import limits
from semantix_passbudget.domain.errors import DomainValidationError
from semantix_passbudget.interfaces.api.body_limit import RequestBodySizeLimit
from semantix_passbudget.interfaces.dto import (
    ComparisonRequest,
    CreateRunRequest,
    HealthResponse,
    RunMetadataResponse,
    RunResultsResponse,
    load_public_fixture,
    parse_fixture_content,
)
from semantix_passbudget.interfaces.lifecycle_dto import (
    CloneScenarioRevisionRequest,
    CreateProfileRequest,
    CreateProfileRevisionRequest,
    CreateScenarioRequest,
    CreateScenarioRevisionRequest,
    PresetsResponse,
    ProfileResponse,
    ProfileRevisionResponse,
    ScenarioResponse,
    ScenarioRevisionResponse,
    SnapshotResponse,
)
from semantix_passbudget.ports.catalog_repository import (
    ProfileHead,
    ProfileRevisionRecord,
    ScenarioHead,
    ScenarioRevisionRecord,
)

# The API is a persistent entry point, so its default tier is SQLite. PostgreSQL is selected
# only by setting PASSBUDGET_DATABASE_URL; see application/composition.py.
application = build_application(default_persistence="sqlite")
service = application.runs
catalog = application.catalog
app = FastAPI(title="SEMANTIX PassBudget", version="0.2.0")
# Bounds the body by declared *and* received length; see interfaces/api/body_limit.py.
app.add_middleware(RequestBodySizeLimit, maximum=limits.MAX_REQUEST_BODY_BYTES)

NOT_FOUND_CODES = {
    "PROFILE_NOT_FOUND",
    "PROFILE_REVISION_NOT_FOUND",
    "SCENARIO_NOT_FOUND",
    "SCENARIO_REVISION_NOT_FOUND",
    "SNAPSHOT_NOT_FOUND",
    "RUN_NOT_FOUND",
}
#: A missing fixture name is a bad request body value, not a missing addressed resource.


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _error_response(
    status_code: int,
    code: str,
    message: str,
    scope: str,
    field_paths: list[str] | None = None,
    details: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "scope": scope,
                "field_paths": field_paths or [],
                "affected_branches": [],
                "details": details or {},
            }
        },
    )


@app.exception_handler(DomainValidationError)
async def domain_error_handler(_request: Request, exc: DomainValidationError) -> JSONResponse:
    status = 404 if exc.detail.code in NOT_FOUND_CODES else 422
    return JSONResponse(status_code=status, content={"error": exc.detail.as_dict()})


@app.exception_handler(RequestValidationError)
async def request_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    field_paths = [".".join(str(part) for part in error["loc"]) for error in exc.errors()]
    return _error_response(
        422,
        "INVALID_REQUEST",
        "Request does not match the typed API contract.",
        "request",
        field_paths,
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(_request: Request, _exc: Exception) -> JSONResponse:
    # The exception is deliberately not rendered: it may carry a database URL or a host path.
    return _error_response(
        500, "INTERNAL_ERROR", "The request could not be completed.", "application"
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Process status and the persistence tier name only.

    The tier name (`memory`, `sqlite`, `postgresql`) is operational information. The database
    path, URL, host and credentials are deliberately not exposed.
    """
    return HealthResponse(status="ok", persistence=application.persistence)


# ------------------------------------------------------------------ catalog


@app.get("/api/v1/presets", response_model=PresetsResponse)
def list_presets() -> Any:
    return catalog.list_presets()


def _profile_revision_response(item: ProfileRevisionRecord) -> dict[str, Any]:
    return {
        "revision_id": item.revision_id,
        "profile_id": item.profile_id,
        "profile_kind": item.profile_kind,
        "revision_no": item.revision_no,
        "lifecycle_status": item.lifecycle_status.value,
        "schema_version": item.schema_version,
        "label": item.label,
        "change_note": item.change_note,
        "based_on_revision_id": item.based_on_revision_id,
        "semantic_hash": item.semantic_hash,
        "published_at": item.published_at,
    }


def _profile_response(
    head: ProfileHead, revisions: tuple[ProfileRevisionRecord, ...]
) -> dict[str, Any]:
    return {
        "profile_id": head.profile_id,
        "stable_key": head.stable_key,
        "kind": head.kind,
        "name": head.name,
        "description": head.description,
        "is_preset": head.is_preset,
        "current_revision_id": head.current_revision_id,
        "revisions": [_profile_revision_response(item) for item in revisions],
    }


@app.post("/api/v1/profiles", status_code=201, response_model=ProfileResponse)
def create_profile(request: CreateProfileRequest) -> Any:
    head = catalog.create_profile(
        stable_key=request.stable_key,
        kind=request.kind,
        name=request.name,
        description=request.description,
        is_preset=request.is_preset,
    )
    return _profile_response(head, ())


@app.get("/api/v1/profiles/{profile_id}", response_model=ProfileResponse)
def get_profile(profile_id: str) -> Any:
    head, revisions = catalog.get_profile(profile_id)
    return _profile_response(head, revisions)


@app.post(
    "/api/v1/profiles/{profile_id}/revisions",
    status_code=201,
    response_model=ProfileRevisionResponse,
)
def create_profile_revision(profile_id: str, request: CreateProfileRevisionRequest) -> Any:
    revision = catalog.create_profile_revision(
        profile_id,
        payload=request.payload,
        label=request.label,
        change_note=request.change_note,
        based_on_revision_id=request.based_on_revision_id,
    )
    return _profile_revision_response(revision)


@app.post("/api/v1/profile-revisions/{revision_id}/publish", response_model=ProfileRevisionResponse)
def publish_profile_revision(revision_id: str) -> Any:
    return _profile_revision_response(
        catalog.publish_profile_revision(revision_id, published_at=_now())
    )


@app.get("/api/v1/profile-revisions/{revision_id}/content")
def get_profile_revision_content(revision_id: str) -> Any:
    """Read-only profile revision payload (mirrors the scenario-revision content route).

    Returns the opaque JSON `payload` the caller stored (e.g. a satellite preset's orbit + display
    name), so the UI can load a saved profile back. The payload is the same synthetic input the
    caller submitted; it carries no credentials, host paths or database identifiers -- the same
    trust boundary as the scenario content route. A missing revision is a 404, never a fabricated
    empty body. This reuses the repository's existing revision lookup and changes no domain rule,
    schema, canonical hash or golden output.
    """
    revision = catalog.get_profile_revision_or_none(revision_id)
    if revision is None:
        return _error_response(
            404,
            "PROFILE_REVISION_NOT_FOUND",
            "No profile revision exists for the supplied identifier.",
            "profile_revision",
            ["revision_id"],
        )
    return {
        "revision_id": revision.revision_id,
        "profile_id": revision.profile_id,
        "profile_kind": revision.profile_kind.value,
        "revision_no": revision.revision_no,
        "lifecycle_status": revision.lifecycle_status.value,
        "schema_version": revision.schema_version,
        "label": revision.label,
        "payload": revision.payload,
    }


# ------------------------------------------------------------------ scenarios


def _scenario_revision_response(item: ScenarioRevisionRecord) -> dict[str, Any]:
    return {
        "revision_id": item.revision_id,
        "scenario_id": item.scenario_id,
        "revision_no": item.revision_no,
        "lifecycle_status": item.lifecycle_status.value,
        "schema_version": item.schema_version,
        "based_on_revision_id": item.based_on_revision_id,
        "semantic_hash": item.semantic_hash,
        "published_at": item.published_at,
    }


def _scenario_response(
    head: ScenarioHead,
    revisions: tuple[ScenarioRevisionRecord, ...],
    run_ids: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "scenario_id": head.scenario_id,
        "stable_key": head.stable_key,
        "name": head.name,
        "description": head.description,
        "is_preset": head.is_preset,
        "current_revision_id": head.current_revision_id,
        "revisions": [_scenario_revision_response(item) for item in revisions],
        "recent_run_ids": list(run_ids),
    }


@app.post("/api/v1/scenarios", status_code=201, response_model=ScenarioResponse)
def create_scenario(request: CreateScenarioRequest) -> Any:
    head, draft = catalog.create_scenario(
        stable_key=request.stable_key,
        name=request.name,
        description=request.description,
        is_preset=request.is_preset,
        content=request.content.model_dump(mode="json"),
    )
    return _scenario_response(head, (draft,), ())


@app.get("/api/v1/scenarios/{scenario_id}", response_model=ScenarioResponse)
def get_scenario(scenario_id: str) -> Any:
    head, revisions, run_ids = catalog.get_scenario(scenario_id)
    return _scenario_response(head, revisions, run_ids)


@app.post(
    "/api/v1/scenarios/{scenario_id}/revisions",
    status_code=201,
    response_model=ScenarioRevisionResponse,
)
def create_scenario_revision(scenario_id: str, request: CreateScenarioRevisionRequest) -> Any:
    revision = catalog.create_scenario_revision(
        scenario_id,
        content=request.content.model_dump(mode="json") if request.content else None,
        based_on_revision_id=request.based_on_revision_id,
    )
    return _scenario_revision_response(revision)


@app.post(
    "/api/v1/scenario-revisions/{revision_id}/publish", response_model=ScenarioRevisionResponse
)
def publish_scenario_revision(revision_id: str) -> Any:
    return _scenario_revision_response(
        catalog.publish_scenario_revision(revision_id, published_at=_now())
    )


@app.post(
    "/api/v1/scenario-revisions/{revision_id}/clone",
    status_code=201,
    response_model=ScenarioResponse,
)
def clone_scenario_revision(revision_id: str, request: CloneScenarioRevisionRequest) -> Any:
    head, draft = catalog.clone_scenario_revision(
        revision_id, stable_key=request.stable_key, name=request.name
    )
    return _scenario_response(head, (draft,), ())


@app.get("/api/v1/scenario-revisions/{revision_id}/content")
def get_scenario_revision_content(revision_id: str) -> Any:
    """Read-only scenario revision content (FE-GAP-01).

    Returns the stored scenario input body (the FixtureDTO the caller previously saved) so the UI
    can restore an edited scenario after a refresh. The body is the same synthetic input the caller
    submitted; it carries no credentials, host paths or database identifiers -- the same trust
    boundary as the existing snapshot and run endpoints. A missing revision is a 404, never a
    fabricated empty body. This reuses the repository's revision lookup and changes no domain rule,
    schema, canonical hash or golden output.
    """
    revision = catalog.get_scenario_revision_or_none(revision_id)
    if revision is None:
        return _error_response(
            404,
            "SCENARIO_REVISION_NOT_FOUND",
            "No scenario revision exists for the supplied identifier.",
            "scenario_revision",
            ["revision_id"],
        )
    return {
        "revision_id": revision.revision_id,
        "scenario_id": revision.scenario_id,
        "revision_no": revision.revision_no,
        "lifecycle_status": revision.lifecycle_status.value,
        "schema_version": revision.schema_version,
        "content": revision.content,
    }


@app.post(
    "/api/v1/scenario-revisions/{revision_id}/snapshots",
    status_code=201,
    response_model=SnapshotResponse,
)
def create_snapshot(revision_id: str) -> Any:
    snapshot = catalog.create_snapshot(revision_id)
    # A snapshot is only executable when the resolved input itself validates. A structural or
    # evidence failure returns the blocked branches instead of a half-valid artifact.
    try:
        parse_fixture_content(snapshot.content["content"]).to_domain().validate()
    except DomainValidationError as exc:
        detail = exc.detail
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    **detail.as_dict(),
                    "details": {
                        **detail.details,
                        "scenario_revision_id": revision_id,
                        "snapshot_promotion": "REJECTED",
                    },
                }
            },
        )
    return {
        "snapshot_id": snapshot.snapshot_id,
        "scenario_revision_id": snapshot.scenario_revision_id,
        "schema_version": snapshot.schema_version,
        "canonicalization_revision": snapshot.canonicalization_revision,
        "input_snapshot_hash": snapshot.content_sha256,
        "validation_status": snapshot.validation_status,
        "validation_code": snapshot.validation_code,
    }


# ------------------------------------------------------------------ runs


@app.post("/api/v1/runs", status_code=201, response_model=RunMetadataResponse)
def create_run(request: CreateRunRequest) -> Any:
    if request.snapshot_id is not None:
        snapshot = catalog.get_snapshot(request.snapshot_id)
        fixture = parse_fixture_content(snapshot.content["content"])
        scenario_revision_id = snapshot.scenario_revision_id
    else:
        fixture = request.snapshot or load_public_fixture(request.fixture or "")
        scenario_revision_id = None
    run = service.run(fixture.to_domain())
    if scenario_revision_id is not None:
        revision = catalog.get_scenario_revision_or_none(scenario_revision_id)
        if revision is not None:
            application.catalog_repository.record_run(revision.scenario_id, run.run_id)
    return RunMetadataResponse.model_validate(run.metadata_dict())


@app.get("/api/v1/runs/{run_id}", response_model=RunMetadataResponse)
def get_run(run_id: str) -> Any:
    run = service.get(run_id)
    if run is None:
        return _error_response(
            404,
            "RUN_NOT_FOUND",
            "No run exists for the supplied identifier.",
            "run",
            ["run_id"],
        )
    return RunMetadataResponse.model_validate(run.metadata_dict())


def _document_unavailable(run_id: str) -> JSONResponse:
    """The active tier stored the typed rows but not the rendered result document.

    Only the optional PostgreSQL tier is in this position: the accepted v0.1 schema has no
    result-document table, and this project does not invent one. Saying so explicitly is better
    than returning an empty object that looks like a computed result.
    """
    return _error_response(
        501,
        "RESULT_DOCUMENT_NOT_PERSISTED",
        "This persistence tier stores typed result rows but not the rendered result document. "
        "Re-run the analysis, or use the default local tier.",
        "run",
        ["run_id"],
        {"persistence": application.persistence, "run_id": run_id},
    )


@app.get("/api/v1/runs/{run_id}/results", response_model=RunResultsResponse)
def get_results(run_id: str) -> Any:
    run = service.get(run_id)
    if run is None:
        return get_run(run_id)
    if not run.result:
        return _document_unavailable(run_id)
    return {
        "run_id": run.run_id,
        "input_snapshot_hash": run.input_snapshot_hash,
        "result_content_hash": run.result_content_hash,
        "result": run.result,
    }


@app.get("/api/v1/runs/{run_id}/report", response_class=PlainTextResponse)
def get_report(run_id: str) -> Any:
    run = service.get(run_id)
    if run is None:
        return get_run(run_id)
    if not run.result:
        return _document_unavailable(run_id)
    return PlainTextResponse(render_report(run.result))


@app.get("/api/v1/runs/{run_id}/daily-budget")
def get_daily_budget(run_id: str) -> Any:
    """Per-UTC-date transfer budget derived from an existing run result (read-only).

    No new physics: the run's already-computed sessions are re-aggregated by the UTC calendar day
    of each session start (see application/daily_budget.py and the F4 contract). Missing run → 404;
    a tier that stored typed rows but no result document → 501 (same boundary as the other result
    views). The result document and its hash are never touched.
    """
    run = service.get(run_id)
    if run is None:
        return get_run(run_id)
    if not run.result:
        return _document_unavailable(run_id)
    window = run.input_snapshot_payload.get("analysis_window")
    payload = daily_budget(run.result, window if isinstance(window, dict) else None)
    payload["run_id"] = run.run_id
    return payload


@app.post("/api/v1/comparisons")
def create_comparison(request: ComparisonRequest) -> Any:
    baseline = service.get(request.baseline_run_id)
    candidate = service.get(request.candidate_run_id)
    if baseline is None or candidate is None:
        missing = request.baseline_run_id if baseline is None else request.candidate_run_id
        return _error_response(
            404,
            "RUN_NOT_FOUND",
            "A comparison run identifier does not exist.",
            "comparison",
            ["baseline_run_id", "candidate_run_id"],
            {"missing_run_id": missing},
        )
    if not baseline.result or not candidate.result:
        return _document_unavailable(
            request.baseline_run_id if not baseline.result else request.candidate_run_id
        )
    return compare_results(baseline.result, candidate.result)
