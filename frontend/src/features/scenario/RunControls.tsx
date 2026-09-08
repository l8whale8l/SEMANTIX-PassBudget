import type { ScenarioDraft } from './draft'
import type { RunPhase } from './useRunScenario'

export interface RunControlsProps {
  draft: ScenarioDraft
  patch: (partial: Partial<ScenarioDraft>) => void
  phase: RunPhase
  hasResult: boolean
  isStale: boolean
  onRun: () => void
}

const PHASE_LABEL: Record<RunPhase, string> = {
  idle: '대기',
  submitting: '실행 요청 중…',
  'loading-results': '결과 불러오는 중…',
  succeeded: '완료',
  failed: '실패',
}

export function RunControls({
  draft,
  patch,
  phase,
  hasResult,
  isStale,
  onRun,
}: RunControlsProps) {
  const inFlight = phase === 'submitting' || phase === 'loading-results'
  // NETWORK_ONLY is solved exactly and the domain rejects a bounded approximation there
  // (EXECUTION_STRATEGY_NOT_APPLICABLE). Show EXACT and disable the control so the displayed value
  // equals what is actually sent — no hidden auto-correction (correction 1).
  const networkOnly = draft.analysisMode === 'NETWORK_ONLY'
  const shownStrategy = networkOnly ? 'EXACT_GLOBAL' : draft.executionStrategy
  return (
    <div className="run-controls">
      <div className="unit-field">
        <label htmlFor="exec-strategy">실행 전략</label>
        <select
          id="exec-strategy"
          value={shownStrategy}
          disabled={inFlight || networkOnly}
          onChange={(e) =>
            patch({ executionStrategy: e.target.value as ScenarioDraft['executionStrategy'] })
          }
        >
          <option value="EXACT_GLOBAL">EXACT_GLOBAL (정확·전역 최적)</option>
          <option value="BOUNDED_APPROXIMATE">BOUNDED_APPROXIMATE (근사)</option>
        </select>
        {networkOnly ? (
          <p className="unit-field__help">NETWORK_ONLY는 정확 해가 있어 EXACT_GLOBAL만 사용합니다.</p>
        ) : null}
      </div>
      <button
        type="button"
        className="btn btn--primary"
        onClick={onRun}
        disabled={inFlight}
        aria-busy={inFlight}
      >
        {inFlight ? PHASE_LABEL[phase] : '실행'}
      </button>
      <span className="run-controls__status" aria-live="polite">
        상태: {PHASE_LABEL[phase]}
      </span>
      {hasResult && isStale ? (
        <span className="run-controls__stale" role="status">
          입력이 변경됨 — 재계산 필요
        </span>
      ) : null}
    </div>
  )
}
