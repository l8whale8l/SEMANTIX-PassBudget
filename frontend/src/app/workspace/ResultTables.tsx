import type { SubmittedRun } from '../../features/scenario/useRunScenario'
import { PassTable } from '../../features/budget/PassTable'
import { DailyBudgetTable } from '../../features/budget/DailyBudgetTable'
import { PayloadDeliveryTable } from '../../features/budget/PayloadDeliveryTable'
import { AllocationSummary } from '../../features/budget/AllocationSummary'
import { ResultWarnings } from '../../features/budget/ResultWarnings'

export type DockTab = 'pass' | 'daily' | 'delivery' | 'basis'

const DOCK_TABS: { id: DockTab; label: string }[] = [
  { id: 'pass', label: '패스' },
  { id: 'daily', label: '일별 예산' },
  { id: 'delivery', label: '출력 전송' },
  { id: 'basis', label: '계산 근거' },
]

export interface ResultTablesProps {
  lastRun: SubmittedRun | null
  selectedPassKey: string | null
  onSelectPass: (key: string | null) => void
  tab: DockTab
  onTabChange: (tab: DockTab) => void
}

/**
 * The tabbed result tables (pass / daily budget / delivery). Shared verbatim by the docked bottom
 * panel and the floating result window so switching between docked and floating never rebuilds the
 * tables or loses the active tab. The `key` on DailyBudgetTable remounts per run to avoid a stale
 * fetch racing a new run.
 */
export function ResultTables({ lastRun, selectedPassKey, onSelectPass, tab, onTabChange }: ResultTablesProps) {
  const result = lastRun?.envelope.result ?? null
  return (
    <div className="results">
      <div className="results__tabs dock__tabs" role="tablist">
        {DOCK_TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={tab === t.id ? 'dock__tab dock__tab--active' : 'dock__tab'}
            onClick={() => onTabChange(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="results__body">
        {!result ? (
          <p className="dock__empty">아직 실행 결과가 없습니다. 상단의 “재계산”을 눌러 계산하세요.</p>
        ) : tab === 'pass' ? (
          <PassTable result={result} selectedPassKey={selectedPassKey} onSelect={onSelectPass} />
        ) : tab === 'daily' ? (
          <DailyBudgetTable key={`daily:${lastRun!.envelope.run_id}`} runId={lastRun!.envelope.run_id} />
        ) : tab === 'basis' ? (
          <ResultWarnings result={result} />
        ) : (
          <>
            <AllocationSummary result={result} />
            <PayloadDeliveryTable result={result} />
          </>
        )}
      </div>
    </div>
  )
}
