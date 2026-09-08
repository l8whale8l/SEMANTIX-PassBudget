// @vitest-environment node
//
// Repeatable full-stack E2E against the REAL backend on the default SQLite tier. Run with:
//   npm run test:e2e     (set PASSBUDGET_PY / PASSBUDGET_REPO when running from an ASCII copy)
//
// Covers the journeys that need a live server + a real restart (the frontend-logic journeys —
// invalid-draft NETWORK_ONLY, referenced-payload blocking, A/B report race — are covered
// deterministically by the component suites).

import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { apiFor, resolvePython, startBackend, type Backend } from './backend'
import orbContent from '../src/features/scenario/presets/PB-GOLDEN-ORB-01.json'

const PORT = 8123
const havePython = resolvePython() !== null

describe.skipIf(!havePython)('full-stack restart persistence (CLOSE-03/04/06, journeys 1/5/6/7)', () => {
  let dir: string
  let dbPath: string
  let backend: Backend

  beforeAll(async () => {
    dir = mkdtempSync(join(tmpdir(), 'pb-e2e-'))
    dbPath = join(dir, 'e2e.sqlite3')
    backend = await startBackend(PORT, dbPath)
  }, 30_000)

  afterAll(async () => {
    await backend?.stop()
    try {
      rmSync(dir, { recursive: true, force: true })
    } catch {
      /* best effort */
    }
  })

  it('runs the golden preset, saves it, survives a full restart, and re-runs to the same hash', async () => {
    let api = apiFor(backend.base)
    expect((await api.health()).persistence).toBe('sqlite')

    // 1) Golden run by fixture id -> baseline hash.
    const baseRun = await api.createRun({ fixture: 'PB-GOLDEN-ORB-01' })
    const baseline = await api.results(baseRun.run_id)
    expect(baseline.result.contact_source).toBe('ORBIT_DERIVED')
    const baselineHash = baseline.result_content_hash

    // 1b) The F4 per-UTC-date budget is a read-only re-aggregation of that run; capture it and its
    //     sum-preservation invariant so we can prove it reproduces byte-identically after a restart.
    const baselineBudget = await api.dailyBudget(baseRun.run_id)
    expect(baselineBudget.aggregation_basis).toBe('UTC_DATE_OF_SESSION_START')
    expect(baselineBudget.sum_preserved).toBe(true)

    // 2) Save the scenario (create -> publish -> snapshot).
    const scenario = await api.createScenario({
      stable_key: `SC-E2E-${Date.now()}`,
      name: 'e2e restart',
      content: orbContent,
    })
    const scenarioId = scenario.scenario_id
    const firstRevisionId = scenario.revisions[0].revision_id
    await api.publish(firstRevisionId)
    await api.snapshot(firstRevisionId)

    // 3) FULL restart: stop the process and start a new one on the same SQLite file.
    await backend.stop()
    backend = await startBackend(PORT, dbPath)
    api = apiFor(backend.base)

    // 4) The scenario survived the restart; read its content back from the server.
    const restored = await api.getScenario(scenarioId)
    expect(restored.name).toBe('e2e restart')
    expect(restored.current_revision_id).toBe(firstRevisionId)
    const content = (await api.getContent(firstRevisionId)).content

    // 5) Re-running the restored content reproduces the identical result hash after the restart.
    const reRun = await api.createRun({ snapshot: content })
    const reResults = await api.results(reRun.run_id)
    expect(reResults.result_content_hash).toBe(baselineHash)

    // 5b) The daily budget derived after the restart matches the pre-restart one exactly. This
    //     proves the read model's analysis window survives the process boundary (the SQLite tier
    //     restores the stored input payload), not only the result document.
    const reBudget = await api.dailyBudget(reRun.run_id)
    expect(reBudget.sum_preserved).toBe(true)
    expect(reBudget.period_scheduled_unique_capacity_bytes).toBe(
      baselineBudget.period_scheduled_unique_capacity_bytes,
    )
    expect(reBudget.days).toEqual(baselineBudget.days)

    // 6) A new revision persists; the original published revision is immutable.
    const edited = structuredClone(content) as Record<string, unknown> & {
      analysis_window: { start: string; end: string }
    }
    edited.analysis_window = { start: '2026-09-03T00:00:00Z', end: '2026-09-03T12:00:00Z' }
    const secondRevision = await api.createRevision(scenarioId, edited)
    await api.publish(secondRevision.revision_id)
    const afterEdit = await api.getScenario(scenarioId)
    expect(afterEdit.revisions).toHaveLength(2)
    expect(afterEdit.current_revision_id).toBe(secondRevision.revision_id)
    const originalStill = (await api.getContent(firstRevisionId)).content as {
      analysis_window: { end: string }
    }
    expect(originalStill.analysis_window.end).toBe('2026-09-04T00:00:00Z') // unchanged
  }, 60_000)

  it('clones a scenario, loads the DRAFT clone via its newest revision, and runs it (CLOSE-04)', async () => {
    const api = apiFor(backend.base)
    const source = await api.createScenario({
      stable_key: `SC-SRC-${Date.now()}`,
      name: 'clone source',
      content: orbContent,
    })
    const sourceRev = source.revisions[0].revision_id
    await api.publish(sourceRev)

    const cloned = await api.clone(sourceRev, { stable_key: `SC-CLONE-${Date.now()}`, name: 'the clone' })
    // A clone is returned as a DRAFT with no published current revision.
    expect(cloned.current_revision_id).toBeNull()

    // Load path: fall back to the newest revision; /content reads a DRAFT.
    const cloneScenario = await api.getScenario(cloned.scenario_id)
    const revisionId = cloneScenario.current_revision_id ?? cloneScenario.revisions.at(-1)!.revision_id
    const cloneContent = (await api.getContent(revisionId)).content

    // The cloned draft runs, and the original published revision is untouched.
    const run = await api.createRun({ snapshot: cloneContent })
    const res = await api.results(run.run_id)
    expect(res.result.contact_source).toBe('ORBIT_DERIVED')
    const sourceAfter = await api.getScenario(source.scenario_id)
    expect(sourceAfter.revisions[0].lifecycle_status).toBe('PUBLISHED')
  }, 60_000)
})
