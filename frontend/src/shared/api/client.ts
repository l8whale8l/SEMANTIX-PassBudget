// The single HTTP boundary to the PassBudget backend.
//
// Every network call goes through here so display components stay free of fetch logic
// (FRONTEND_IMPLEMENTATION_SPEC §6). The server is reached via the same-origin dev proxy, so paths
// are relative ("/api/...", "/health"). Server identifiers (run_id, hashes) are used verbatim; the
// client never invents one.

import type {
  ApiErrorBody,
  ComparisonResponse,
  CreateRunRequest,
  DailyBudget,
  FixtureContent,
  ProfileResponse,
  ProfileRevisionContent,
  ProfileRevisionMeta,
  RunMetadata,
  RunResultsEnvelope,
  ScenarioResponse,
  ScenarioRevisionContent,
  ScenarioRevisionMeta,
  ProfilePresetPayload,
  SnapshotResponse,
} from './types'
import { parseDailyBudget, parseRunResultsEnvelope } from './parseResult'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly scope: string
  readonly fieldPaths: string[]
  readonly details: Record<string, unknown>
  constructor(
    status: number,
    code: string,
    message: string,
    scope: string = 'application',
    fieldPaths: string[] = [],
    details: Record<string, unknown> = {},
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.scope = scope
    this.fieldPaths = fieldPaths
    this.details = details
  }
}

/** A transport-level failure (offline, DNS, proxy down) with no HTTP response at all. */
export class NetworkError extends Error {
  /** Whether the request may have reached the server despite the client seeing no response. */
  readonly possiblyDelivered: boolean
  constructor(message: string, possiblyDelivered: boolean) {
    super(message)
    this.name = 'NetworkError'
    this.possiblyDelivered = possiblyDelivered
  }
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  return (
    typeof value === 'object' &&
    value !== null &&
    'error' in value &&
    typeof (value as ApiErrorBody).error?.code === 'string'
  )
}

async function toApiError(response: Response): Promise<ApiError> {
  // The error envelope is the normal case, but the body-size middleware (413) and some proxy
  // failures return plain text or nothing. Fall back to a safe generic error either way; never
  // present a failed request as a success (FRONTEND_API_INTEGRATION §5).
  let body: unknown = null
  const text = await response.text().catch(() => '')
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = null
    }
  }
  if (isErrorBody(body)) {
    const e = body.error
    return new ApiError(response.status, e.code, e.message, e.scope, e.field_paths, e.details)
  }
  return new ApiError(
    response.status,
    `HTTP_${response.status}`,
    genericMessageForStatus(response.status),
    'application',
  )
}

function genericMessageForStatus(status: number): string {
  if (status === 413) return '요청 본문이 서버 상한을 초과했습니다 (원문이 아니라 요청 메타데이터 크기).'
  if (status === 404) return '요청한 리소스를 찾을 수 없습니다.'
  if (status === 501) return '이 저장 계층은 렌더된 결과 문서를 보관하지 않습니다.'
  if (status >= 500) return '서버에서 요청을 완료하지 못했습니다.'
  return `요청이 거부되었습니다 (HTTP ${status}).`
}

async function requestJson<T>(
  path: string,
  init: RequestInit,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, { ...init, signal })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    // A POST that never got a response may still have been applied on the server, so callers must
    // not blindly retry create calls (FRONTEND_API_INTEGRATION §1).
    const possiblyDelivered = (init.method ?? 'GET').toUpperCase() !== 'GET'
    throw new NetworkError('네트워크 연결에 실패했습니다.', possiblyDelivered)
  }
  if (!response.ok) {
    throw await toApiError(response)
  }
  return (await response.json()) as T
}

export interface HealthResponse {
  status: string
  persistence: string
}

export const api = {
  async health(signal?: AbortSignal): Promise<HealthResponse> {
    return requestJson<HealthResponse>('/health', { method: 'GET' }, signal)
  },

  async createRun(request: CreateRunRequest, signal?: AbortSignal): Promise<RunMetadata> {
    return requestJson<RunMetadata>(
      '/api/v1/runs',
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(request),
      },
      signal,
    )
  },

  async getRunResults(runId: string, signal?: AbortSignal): Promise<RunResultsEnvelope> {
    const raw = await requestJson<unknown>(
      `/api/v1/runs/${encodeURIComponent(runId)}/results`,
      { method: 'GET' },
      signal,
    )
    // Validate the free-form result against the contract before the UI trusts a field.
    return parseRunResultsEnvelope(raw)
  },

  async getDailyBudget(runId: string, signal?: AbortSignal): Promise<DailyBudget> {
    const raw = await requestJson<unknown>(
      `/api/v1/runs/${encodeURIComponent(runId)}/daily-budget`,
      { method: 'GET' },
      signal,
    )
    return parseDailyBudget(raw)
  },

  // ---- lifecycle (F3) -------------------------------------------------------------------------

  async createScenario(
    body: { stable_key: string; name: string; content: FixtureContent; description?: string },
    signal?: AbortSignal,
  ): Promise<ScenarioResponse> {
    return postJson<ScenarioResponse>('/api/v1/scenarios', body, signal)
  },

  async createScenarioRevision(
    scenarioId: string,
    body: { content?: FixtureContent; based_on_revision_id?: string },
    signal?: AbortSignal,
  ): Promise<ScenarioRevisionMeta> {
    return postJson<ScenarioRevisionMeta>(
      `/api/v1/scenarios/${encodeURIComponent(scenarioId)}/revisions`,
      body,
      signal,
    )
  },

  async publishScenarioRevision(revisionId: string, signal?: AbortSignal): Promise<ScenarioRevisionMeta> {
    return postJson<ScenarioRevisionMeta>(
      `/api/v1/scenario-revisions/${encodeURIComponent(revisionId)}/publish`,
      {},
      signal,
    )
  },

  async cloneScenarioRevision(
    revisionId: string,
    body: { stable_key: string; name: string },
    signal?: AbortSignal,
  ): Promise<ScenarioResponse> {
    return postJson<ScenarioResponse>(
      `/api/v1/scenario-revisions/${encodeURIComponent(revisionId)}/clone`,
      body,
      signal,
    )
  },

  async createSnapshot(revisionId: string, signal?: AbortSignal): Promise<SnapshotResponse> {
    return postJson<SnapshotResponse>(
      `/api/v1/scenario-revisions/${encodeURIComponent(revisionId)}/snapshots`,
      {},
      signal,
    )
  },

  async getScenario(scenarioId: string, signal?: AbortSignal): Promise<ScenarioResponse> {
    return requestJson<ScenarioResponse>(
      `/api/v1/scenarios/${encodeURIComponent(scenarioId)}`,
      { method: 'GET' },
      signal,
    )
  },

  async getRevisionContent(revisionId: string, signal?: AbortSignal): Promise<ScenarioRevisionContent> {
    return requestJson<ScenarioRevisionContent>(
      `/api/v1/scenario-revisions/${encodeURIComponent(revisionId)}/content`,
      { method: 'GET' },
      signal,
    )
  },

  // ---- profiles (satellite presets) — reuse the generic profile lifecycle (SQLite-persistent) ----

  async createProfile(
    body: { stable_key: string; kind: string; name: string; description?: string; is_preset?: boolean },
    signal?: AbortSignal,
  ): Promise<ProfileResponse> {
    return postJson<ProfileResponse>('/api/v1/profiles', body, signal)
  },

  async createProfileRevision(
    profileId: string,
    body: { label: string; payload: ProfilePresetPayload; change_note?: string; based_on_revision_id?: string },
    signal?: AbortSignal,
  ): Promise<ProfileRevisionMeta> {
    return postJson<ProfileRevisionMeta>(
      `/api/v1/profiles/${encodeURIComponent(profileId)}/revisions`,
      body,
      signal,
    )
  },

  async publishProfileRevision(revisionId: string, signal?: AbortSignal): Promise<ProfileRevisionMeta> {
    return postJson<ProfileRevisionMeta>(
      `/api/v1/profile-revisions/${encodeURIComponent(revisionId)}/publish`,
      {},
      signal,
    )
  },

  async getProfile(profileId: string, signal?: AbortSignal): Promise<ProfileResponse> {
    return requestJson<ProfileResponse>(
      `/api/v1/profiles/${encodeURIComponent(profileId)}`,
      { method: 'GET' },
      signal,
    )
  },

  async getProfileRevisionContent(revisionId: string, signal?: AbortSignal): Promise<ProfileRevisionContent> {
    return requestJson<ProfileRevisionContent>(
      `/api/v1/profile-revisions/${encodeURIComponent(revisionId)}/content`,
      { method: 'GET' },
      signal,
    )
  },

  async createComparison(
    baselineRunId: string,
    candidateRunId: string,
    signal?: AbortSignal,
  ): Promise<ComparisonResponse> {
    return postJson<ComparisonResponse>(
      '/api/v1/comparisons',
      { baseline_run_id: baselineRunId, candidate_run_id: candidateRunId },
      signal,
    )
  },

  async getReportText(runId: string, signal?: AbortSignal): Promise<string> {
    const response = await fetch(`/api/v1/runs/${encodeURIComponent(runId)}/report`, {
      method: 'GET',
      signal,
    }).catch((err) => {
      if (err instanceof DOMException && err.name === 'AbortError') throw err
      throw new NetworkError('네트워크 연결에 실패했습니다.', false)
    })
    if (!response.ok) throw await toApiError(response)
    return response.text()
  },
}

async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return requestJson<T>(
    path,
    { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) },
    signal,
  )
}
