// Execution state machine for a single scenario workspace.
//
// Handles the concurrency hazards called out in FRONTEND_IMPLEMENTATION_SPEC §6 and FE-05/FE-06:
//   * Only the most recently submitted request may write results. A late response from an earlier
//     run is discarded, never shown as the current answer.
//   * A superseded in-flight request is aborted on the client (display cancel only — the server
//     run is synchronous and not actually cancelled).
//   * HTTP success and analysis success are distinct: results are fetched and validated before the
//     state becomes `succeeded`.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, NetworkError } from '../../shared/api/client'
import type {
  CreateRunRequest,
  FixtureContent,
  RunMetadata,
  RunResultsEnvelope,
} from '../../shared/api/types'

export type RunPhase = 'idle' | 'submitting' | 'loading-results' | 'succeeded' | 'failed'

/** The input conditions captured at submit time, so a kept result shows its own context, not the
 *  current (possibly edited) draft (correction 4). */
export interface SubmittedContext {
  readonly analysisMode: string
  readonly windowStart: string
  readonly windowEnd: string
  readonly activeStationKeys: readonly string[]
  /** The exact scenario body that was run — the globe reads station geometry and orbit from it, so
   *  it shows the run's geometry, not the possibly-edited current draft. Optional so other
   *  constructors (tests) need not supply it. */
  readonly content?: FixtureContent
}

export interface SubmittedRun {
  /** Local identity of the exact input that was submitted (for stale comparison). */
  readonly inputIdentity: string
  readonly context: SubmittedContext
  readonly metadata: RunMetadata
  readonly envelope: RunResultsEnvelope
}

export interface RunScenarioState {
  phase: RunPhase
  /** The last successful run and the input it corresponds to. Kept across later edits. */
  lastRun: SubmittedRun | null
  /** This session's successful runs, newest first (bounded), for comparison and history. */
  history: SubmittedRun[]
  error: ApiError | NetworkError | Error | null
  run: (request: CreateRunRequest, inputIdentity: string, context: SubmittedContext) => void
  reset: () => void
}

const MAX_HISTORY = 20

export function useRunScenario(): RunScenarioState {
  const [phase, setPhase] = useState<RunPhase>('idle')
  const [lastRun, setLastRun] = useState<SubmittedRun | null>(null)
  const [history, setHistory] = useState<SubmittedRun[]>([])
  const [error, setError] = useState<RunScenarioState['error']>(null)

  const seqRef = useRef(0)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    return () => abortRef.current?.abort()
  }, [])

  const run = useCallback(
    (request: CreateRunRequest, inputIdentity: string, context: SubmittedContext) => {
      const seq = ++seqRef.current
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller
      // A response is applied only if it belongs to the newest submit. This holds even when a stale
      // response ignores its AbortSignal and resolves late: the seq check discards it (FE-06).
      const isCurrent = () => seqRef.current === seq

      setError(null)
      setPhase('submitting')

      void (async () => {
        try {
          const metadata = await api.createRun(request, controller.signal)
          if (!isCurrent()) return
          setPhase('loading-results')
          const envelope = await api.getRunResults(metadata.run_id, controller.signal)
          if (!isCurrent()) return
          const submitted: SubmittedRun = { inputIdentity, context, metadata, envelope }
          setLastRun(submitted)
          setHistory((h) => [submitted, ...h].slice(0, MAX_HISTORY))
          setPhase('succeeded')
        } catch (err) {
          if (err instanceof DOMException && err.name === 'AbortError') return
          if (!isCurrent()) return
          setError(err as Error)
          setPhase('failed')
        }
      })()
    },
    [],
  )

  const reset = useCallback(() => {
    seqRef.current++
    abortRef.current?.abort()
    setPhase('idle')
    setLastRun(null)
    setError(null)
  }, [])

  return { phase, lastRun, history, error, run, reset }
}
