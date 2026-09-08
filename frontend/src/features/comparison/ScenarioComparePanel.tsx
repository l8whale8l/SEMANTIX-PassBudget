import { useState } from 'react'
import type { SubmittedRun } from '../scenario/useRunScenario'
import type { ComparisonResponse } from '../../shared/api/types'
import { api, ApiError, NetworkError } from '../../shared/api/client'
import { BudgetDeltaSummary } from './BudgetDeltaSummary'
import { StatusPanel } from '../../shared/ui/StatusPanel'

export interface ScenarioComparePanelProps {
  history: SubmittedRun[]
}

function runLabel(run: SubmittedRun): string {
  return `${run.metadata.run_id.slice(0, 8)}… · ${run.context.analysisMode} · 지상국 ${run.context.activeStationKeys.length}`
}

export function ScenarioComparePanel({ history }: ScenarioComparePanelProps) {
  const [baselineId, setBaselineId] = useState('')
  const [candidateId, setCandidateId] = useState('')
  const [comparison, setComparison] = useState<ComparisonResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (history.length < 2) {
    return (
      <section className="card">
        <h3>실행 비교</h3>
        <p className="hint">
          비교하려면 이번 세션에서 최소 두 번 실행하세요(예: 기준 실행 후 지상국·가정을 한 가지 바꿔
          재실행).
        </p>
      </section>
    )
  }

  // A sync handler that attaches .catch synchronously — the rejection can never be momentarily
  // unhandled, and React is never handed a rejecting promise from the event handler.
  const compare = () => {
    if (!baselineId || !candidateId || baselineId === candidateId) {
      setError('서로 다른 두 실행을 선택하세요.')
      return
    }
    setBusy(true)
    setError(null)
    api
      .createComparison(baselineId, candidateId)
      .then((result) => setComparison(result))
      .catch((e: unknown) => {
        setComparison(null)
        setError(
          e instanceof ApiError
            ? `[${e.code}] ${e.message}`
            : e instanceof NetworkError
              ? e.message
              : (e as Error).message,
        )
      })
      .finally(() => setBusy(false))
  }

  const baseline = history.find((r) => r.metadata.run_id === baselineId)
  const candidate = history.find((r) => r.metadata.run_id === candidateId)

  return (
    <section className="card" aria-labelledby="compare-title">
      <h3 id="compare-title">실행 비교</h3>
      <div className="row">
        <div className="unit-field">
          <label htmlFor="cmp-baseline">기준 실행</label>
          <select id="cmp-baseline" value={baselineId} onChange={(e) => setBaselineId(e.target.value)}>
            <option value="">선택…</option>
            {history.map((r) => (
              <option key={r.metadata.run_id} value={r.metadata.run_id}>
                {runLabel(r)}
              </option>
            ))}
          </select>
        </div>
        <div className="unit-field">
          <label htmlFor="cmp-candidate">변경 실행</label>
          <select id="cmp-candidate" value={candidateId} onChange={(e) => setCandidateId(e.target.value)}>
            <option value="">선택…</option>
            {history.map((r) => (
              <option key={r.metadata.run_id} value={r.metadata.run_id}>
                {runLabel(r)}
              </option>
            ))}
          </select>
        </div>
      </div>
      <button type="button" className="btn btn--primary" onClick={compare} disabled={busy}>
        비교 실행
      </button>

      {error ? (
        <StatusPanel kind="error" title="비교 실패">
          {error}
        </StatusPanel>
      ) : null}
      {comparison && baseline && candidate ? (
        <BudgetDeltaSummary
          comparison={comparison}
          baselineLabel={runLabel(baseline)}
          candidateLabel={runLabel(candidate)}
        />
      ) : null}
    </section>
  )
}
