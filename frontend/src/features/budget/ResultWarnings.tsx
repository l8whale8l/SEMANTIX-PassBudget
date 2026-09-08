import type { RunResult } from '../../shared/api/types'

export interface ResultWarningsProps {
  result: RunResult
}

const WARNING_TEXT: Record<string, string> = {
  NOT_A_COMMAND_PLAN: '명령 계획이 아닙니다.',
  NOT_A_GROUND_STATION_RESERVATION: '지상국 예약이 아닙니다.',
  NOT_GROUND_VERIFIED: '지상 검증된 결과가 아닙니다.',
  NO_OPERATIONS_ELIGIBILITY_DECISION: '운용 승인 판단이 아닙니다.',
  PROXY_DEPENDENT_RESULT: '프록시(가정) 값에 의존하는 결과입니다.',
  UNMODELED_PHYSICAL_CONSTRAINTS: '모델링되지 않은 물리적 제약이 있습니다.',
}

export function ResultWarnings({ result }: ResultWarningsProps) {
  const warnings = result.warnings
  return (
    <section className="card card--notice" aria-labelledby="warnings-title">
      <h3 id="warnings-title">가정과 한계</h3>
      <p className="safety-notice">{result.safety_notice}</p>
      {warnings.length > 0 ? (
        <ul className="warning-list">
          {warnings.map((w) => (
            <li key={w.code}>
              <span className="mono">{w.code}</span>
              {WARNING_TEXT[w.code] ? ` — ${WARNING_TEXT[w.code]}` : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="hint">추가 경고 없음.</p>
      )}
    </section>
  )
}
