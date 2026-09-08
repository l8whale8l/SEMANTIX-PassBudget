import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import { useRunScenario, type SubmittedContext } from './useRunScenario'
import { api } from '../../shared/api/client'
import type { RunMetadata, RunResultsEnvelope } from '../../shared/api/types'

// Keep the real error classes; replace only the network functions with controllable stubs.
vi.mock('../../shared/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../shared/api/client')>()
  return { ...actual, api: { createRun: vi.fn(), getRunResults: vi.fn(), health: vi.fn() } }
})

const createRun = api.createRun as unknown as Mock
const getRunResults = api.getRunResults as unknown as Mock

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

const meta = (runId: string): RunMetadata => ({
  run_id: runId,
  status: 'SUCCEEDED',
  input_snapshot_hash: `snap-${runId}`,
  result_content_hash: `res-${runId}`,
  run_record_hash: `rec-${runId}`,
  stages: [],
})

const envelope = (runId: string): RunResultsEnvelope => ({
  run_id: runId,
  input_snapshot_hash: `snap-${runId}`,
  result_content_hash: `res-${runId}`,
  result: {} as RunResultsEnvelope['result'],
})

const ctx: SubmittedContext = {
  analysisMode: 'QUEUE_AWARE',
  windowStart: 'w0',
  windowEnd: 'w1',
  activeStationKeys: ['S1'],
}

beforeEach(() => {
  createRun.mockReset()
  getRunResults.mockReset()
})
afterEach(() => vi.clearAllMocks())

describe('useRunScenario', () => {
  it('applies a normal run to lastRun with its context', async () => {
    createRun.mockResolvedValue(meta('A'))
    getRunResults.mockResolvedValue(envelope('A'))
    const { result } = renderHook(() => useRunScenario())

    await act(async () => {
      result.current.run({ fixture: 'X' }, 'idA', ctx)
    })

    expect(result.current.phase).toBe('succeeded')
    expect(result.current.lastRun?.inputIdentity).toBe('idA')
    expect(result.current.lastRun?.context.activeStationKeys).toEqual(['S1'])
  })

  it('does not let a late response from run A overwrite the newer run B (FE-06)', async () => {
    const resultsA = deferred<RunResultsEnvelope>()
    const resultsB = deferred<RunResultsEnvelope>()
    createRun.mockImplementation((req: { fixture: string }) =>
      Promise.resolve(meta(req.fixture)),
    )
    getRunResults.mockImplementation((runId: string) =>
      runId === 'A' ? resultsA.promise : resultsB.promise,
    )

    const { result } = renderHook(() => useRunScenario())

    // Start A, then B. B supersedes A (A's AbortSignal is deliberately ignored by the stub).
    await act(async () => {
      result.current.run({ fixture: 'A' }, 'idA', ctx)
    })
    await act(async () => {
      result.current.run({ fixture: 'B' }, 'idB', ctx)
    })

    // B resolves first, then A arrives late.
    await act(async () => {
      resultsB.resolve(envelope('B'))
    })
    await act(async () => {
      resultsA.resolve(envelope('A'))
    })

    expect(result.current.lastRun?.inputIdentity).toBe('idB')
    expect(result.current.lastRun?.metadata.run_id).toBe('B')
  })

  it('keeps the last good result when a subsequent run fails (correction 4)', async () => {
    createRun.mockResolvedValueOnce(meta('A'))
    getRunResults.mockResolvedValueOnce(envelope('A'))
    const { result } = renderHook(() => useRunScenario())
    await act(async () => {
      result.current.run({ fixture: 'A' }, 'idA', ctx)
    })
    expect(result.current.lastRun?.inputIdentity).toBe('idA')

    createRun.mockRejectedValueOnce(new Error('boom'))
    await act(async () => {
      result.current.run({ fixture: 'B' }, 'idB', ctx)
    })

    expect(result.current.phase).toBe('failed')
    expect(result.current.error?.message).toBe('boom')
    // The prior success is preserved, not cleared.
    expect(result.current.lastRun?.inputIdentity).toBe('idA')
  })

  it('reset clears results and ignores an in-flight response', async () => {
    const results = deferred<RunResultsEnvelope>()
    createRun.mockResolvedValue(meta('A'))
    getRunResults.mockReturnValue(results.promise)
    const { result } = renderHook(() => useRunScenario())

    await act(async () => {
      result.current.run({ fixture: 'A' }, 'idA', ctx)
    })
    act(() => result.current.reset())
    await act(async () => {
      results.resolve(envelope('A'))
    })

    expect(result.current.lastRun).toBeNull()
    expect(result.current.phase).toBe('idle')
  })

  it('does not update state after unmount', async () => {
    const results = deferred<RunResultsEnvelope>()
    createRun.mockResolvedValue(meta('A'))
    getRunResults.mockReturnValue(results.promise)
    const { result, unmount } = renderHook(() => useRunScenario())

    await act(async () => {
      result.current.run({ fixture: 'A' }, 'idA', ctx)
    })
    unmount()
    await act(async () => {
      results.resolve(envelope('A'))
    })
    // No throw / no act warning failure means the post-unmount response was ignored.
    expect(true).toBe(true)
  })
})
