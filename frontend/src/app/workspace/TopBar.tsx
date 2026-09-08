import { useEffect, useState } from 'react'

import { api } from '../../shared/api/client'
import type { ScenarioDraft } from '../../features/scenario/draft'
import type { RunPhase, SubmittedRun } from '../../features/scenario/useRunScenario'
import { ScenarioMenu } from './ScenarioMenu'

export interface TopBarProps {
  draft: ScenarioDraft
  phase: RunPhase
  lastRun: SubmittedRun | null
  isStale: boolean
  unsaved: boolean
  buildError: string | null
  onRun: () => void
  onNewScenario: () => void
  onRenameScenario: (name: string) => void
  onOpenLibrary: (mode: 'open' | 'save') => void
}

const PHASE_LABEL: Record<RunPhase, string> = {
  idle: '대기',
  submitting: '실행 요청 중…',
  'loading-results': '결과 불러오는 중…',
  succeeded: '완료',
  failed: '실패',
}

/** Colour tone for the run-phase status dot (used only before a run has a calculation status). */
function phaseTone(phase: RunPhase): 'ok' | 'warn' | 'danger' | 'accent' | 'muted' {
  switch (phase) {
    case 'succeeded':
      return 'ok'
    case 'failed':
      return 'danger'
    case 'submitting':
    case 'loading-results':
      return 'accent'
    default:
      return 'muted'
  }
}

type HealthState =
  | { kind: 'checking' }
  | { kind: 'ok'; persistence: string }
  | { kind: 'down' }

function useHealth(): HealthState {
  const [state, setState] = useState<HealthState>({ kind: 'checking' })
  useEffect(() => {
    const controller = new AbortController()
    api
      .health(controller.signal)
      .then((h) => setState({ kind: 'ok', persistence: h.persistence }))
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setState({ kind: 'down' })
      })
    return () => controller.abort()
  }, [])
  return state
}

export function TopBar({
  draft,
  phase,
  lastRun,
  isStale,
  unsaved,
  buildError,
  onRun,
  onNewScenario,
  onRenameScenario,
  onOpenLibrary,
}: TopBarProps) {
  const health = useHealth()
  const inFlight = phase === 'submitting' || phase === 'loading-results'
  const calcStatus = lastRun?.envelope.result.calculation_status ?? null

  return (
    <header className="topbar">
      <div className="topbar__brand">
        <span className="topbar__product">SEMANTIX PassBudget</span>
        <ScenarioMenu
          name={draft.scenarioName}
          saved={draft.savedScenarioId != null}
          unsaved={unsaved}
          onNew={onNewScenario}
          onRename={onRenameScenario}
          onOpenLibrary={onOpenLibrary}
        />
      </div>

      <div className="topbar__status" aria-live="polite">
        {unsaved ? (
          <span
            className="topbar__dot topbar__dot--muted"
            role="img"
            aria-label="저장되지 않은 변경"
            title="저장되지 않은 변경 — 저장되지 않은 편집이 있습니다 (계산 상태와는 별개)"
          />
        ) : null}
        {buildError ? (
          <span
            className="topbar__dot topbar__dot--danger"
            role="img"
            aria-label="입력 오류 — 재계산 불가"
            title="입력 오류 — 재계산 불가"
          />
        ) : calcStatus ? (
          <span
            className={
              calcStatus === 'COMPUTED' ? 'topbar__dot topbar__dot--ok' : 'topbar__dot topbar__dot--warn'
            }
            role="img"
            aria-label={calcStatus === 'COMPUTED' ? '계산 완료' : `계산 상태 ${calcStatus}`}
            title={
              calcStatus === 'COMPUTED'
                ? '계산 완료 (COMPUTED)'
                : `계산 상태 ${calcStatus} — 확정 예산이 아닐 수 있습니다`
            }
          />
        ) : (
          <span
            className={`topbar__dot topbar__dot--${phaseTone(phase)}`}
            role="img"
            aria-label={PHASE_LABEL[phase]}
            title={PHASE_LABEL[phase]}
          />
        )}
        {lastRun && isStale ? (
          <span
            className="topbar__dot topbar__dot--warn"
            role="img"
            aria-label="재계산 필요"
            title="입력 변경됨 — 재계산 필요"
          />
        ) : null}
      </div>

      <div className="topbar__right">
        <span
          className={
            health.kind === 'ok'
              ? 'topbar__health topbar__health--ok'
              : health.kind === 'down'
                ? 'topbar__health topbar__health--down'
                : 'topbar__health'
          }
          role="status"
          title={
            health.kind === 'ok'
              ? `서버 연결됨 · 저장계층 ${health.persistence}${
                  health.persistence === 'memory' ? ' (임시 — 서버 재시작 시 시나리오가 초기화됩니다)' : ''
                }`
              : health.kind === 'down'
                ? '백엔드에 연결하지 못했습니다.'
                : '백엔드 상태 확인 중'
          }
        >
          {health.kind === 'ok'
            ? '서버 연결됨'
            : health.kind === 'down'
              ? '서버 연결 안됨'
              : '서버 확인 중…'}
          {health.kind === 'ok' && health.persistence === 'memory' ? (
            <span className="topbar__persist-note" title="이 서버는 임시 저장 모드입니다. 재시작하면 저장한 시나리오가 사라질 수 있어요.">
              임시 저장
            </span>
          ) : null}
        </span>
        <button
          type="button"
          className="btn btn--primary"
          onClick={onRun}
          disabled={inFlight || !!buildError}
          aria-busy={inFlight}
        >
          {inFlight ? PHASE_LABEL[phase] : lastRun ? '재계산' : '실행'}
        </button>
      </div>
    </header>
  )
}
