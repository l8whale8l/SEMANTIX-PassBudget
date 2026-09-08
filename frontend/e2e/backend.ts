// A repeatable backend harness for the E2E suite.
//
// It spawns the REAL Python API (uvicorn) on an isolated port and SQLite file, so the tests drive
// the whole stack — frontend request shapes → FastAPI → SQLite catalog — and can stop and restart
// the process to prove persistence. If the backend cannot be launched in this environment the suite
// skips with a clear reason rather than passing silently.
//
// Configuration (all optional; sensible defaults for running from the repo's frontend dir):
//   PASSBUDGET_PY   — python executable          (default: ../.venv/Scripts/python.exe | ../.venv/bin/python)
//   PASSBUDGET_REPO — repo root (uvicorn cwd)    (default: ..)

import { spawn, type ChildProcess } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

export function resolvePython(): string | null {
  const explicit = process.env.PASSBUDGET_PY
  if (explicit) return existsSync(explicit) ? explicit : null
  const candidates = [
    resolve(process.cwd(), '..', '.venv', 'Scripts', 'python.exe'),
    resolve(process.cwd(), '..', '.venv', 'bin', 'python'),
  ]
  return candidates.find((p) => existsSync(p)) ?? null
}

export function repoRoot(): string {
  return process.env.PASSBUDGET_REPO ? resolve(process.env.PASSBUDGET_REPO) : resolve(process.cwd(), '..')
}

export interface Backend {
  readonly base: string
  stop: () => Promise<void>
}

async function waitForHealth(base: string, timeoutMs = 20_000): Promise<void> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${base}/health`)
      if (res.ok) return
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 300))
  }
  throw new Error(`backend did not become healthy at ${base} within ${timeoutMs}ms`)
}

/** Start uvicorn on `port` against `sqlitePath` (SQLite tier), waiting until /health responds. */
export async function startBackend(port: number, sqlitePath: string): Promise<Backend> {
  const python = resolvePython()
  if (!python) throw new Error('SKIP: python venv not found (set PASSBUDGET_PY)')
  const base = `http://127.0.0.1:${port}`
  const child: ChildProcess = spawn(
    python,
    [
      '-m',
      'uvicorn',
      'semantix_passbudget.interfaces.api.app:app',
      '--host',
      '127.0.0.1',
      '--port',
      String(port),
      '--log-level',
      'warning',
    ],
    {
      cwd: repoRoot(),
      env: {
        ...process.env,
        PASSBUDGET_PERSISTENCE: 'sqlite',
        PASSBUDGET_SQLITE_PATH: sqlitePath,
        PASSBUDGET_DATABASE_URL: '',
        PYTHONIOENCODING: 'utf-8',
      },
      stdio: 'ignore',
    },
  )
  const stop = () =>
    new Promise<void>((res) => {
      if (child.exitCode !== null || child.killed) return res()
      child.once('exit', () => res())
      child.kill()
      // Windows sometimes needs a beat; force after a grace period.
      setTimeout(() => {
        if (child.exitCode === null) child.kill('SIGKILL')
        res()
      }, 2000)
    })
  try {
    await waitForHealth(base)
  } catch (err) {
    await stop()
    throw err
  }
  return { base, stop }
}

/** Minimal typed fetch helpers mirroring the frontend client's request shapes. */
export function apiFor(base: string) {
  async function json<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${base}${path}`, {
      ...init,
      headers: init?.body ? { 'content-type': 'application/json' } : undefined,
    })
    if (!res.ok) {
      throw new Error(`${init?.method ?? 'GET'} ${path} -> ${res.status}: ${await res.text()}`)
    }
    return (await res.json()) as T
  }
  return {
    health: () => json<{ status: string; persistence: string }>('/health'),
    createRun: (body: unknown) =>
      json<{ run_id: string }>('/api/v1/runs', { method: 'POST', body: JSON.stringify(body) }),
    results: (runId: string) =>
      json<{ result_content_hash: string; input_snapshot_hash: string; result: Record<string, unknown> }>(
        `/api/v1/runs/${runId}/results`,
      ),
    dailyBudget: (runId: string) =>
      json<{
        run_id: string
        aggregation_basis: string
        sum_preserved: boolean
        period_scheduled_unique_capacity_bytes: number | null
        days: {
          utc_date: string
          is_partial: boolean
          scheduled_session_count: number
          scheduled_capacity_bytes: number
        }[]
      }>(`/api/v1/runs/${runId}/daily-budget`),
    createScenario: (body: unknown) =>
      json<{ scenario_id: string; revisions: { revision_id: string }[] }>('/api/v1/scenarios', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    publish: (revId: string) =>
      json<unknown>(`/api/v1/scenario-revisions/${revId}/publish`, { method: 'POST', body: '{}' }),
    snapshot: (revId: string) =>
      json<{ snapshot_id: string }>(`/api/v1/scenario-revisions/${revId}/snapshots`, {
        method: 'POST',
        body: '{}',
      }),
    getScenario: (id: string) =>
      json<{
        scenario_id: string
        name: string
        current_revision_id: string | null
        revisions: { revision_id: string; revision_no: number; lifecycle_status: string }[]
      }>(`/api/v1/scenarios/${id}`),
    getContent: (revId: string) =>
      json<{ content: Record<string, unknown> }>(`/api/v1/scenario-revisions/${revId}/content`),
    createRevision: (scenarioId: string, content: unknown) =>
      json<{ revision_id: string; revision_no: number }>(
        `/api/v1/scenarios/${scenarioId}/revisions`,
        { method: 'POST', body: JSON.stringify({ content }) },
      ),
    clone: (revId: string, body: unknown) =>
      json<{ scenario_id: string; current_revision_id: string | null; revisions: { revision_id: string }[] }>(
        `/api/v1/scenario-revisions/${revId}/clone`,
        { method: 'POST', body: JSON.stringify(body) },
      ),
  }
}
