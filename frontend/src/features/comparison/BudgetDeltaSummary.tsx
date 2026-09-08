import type { ComparisonMetric, ComparisonResponse } from '../../shared/api/types'
import { bytesToMbDisplay } from '../../shared/format/units'
import { AssumptionBadge } from '../../shared/ui/AssumptionBadge'

export interface BudgetDeltaSummaryProps {
  comparison: ComparisonResponse
  baselineLabel: string
  candidateLabel: string
}

function fmtValue(v: number | null, unit: string): string {
  if (v === null) return '해당 없음'
  if (!Number.isSafeInteger(v)) return '표시 불가'
  return unit === 'BYTE' ? `${bytesToMbDisplay(v)} MB` : String(v)
}

function fmtRatio(m: ComparisonMetric): string {
  if (!m.comparable || !m.candidate_to_baseline_ratio) return '—'
  const { numerator, denominator } = m.candidate_to_baseline_ratio
  const num = Number(numerator)
  const den = Number(denominator)
  if (!den) return '—'
  // Display-only percentage; the exact rational is preserved in the API response.
  return `${((num / den) * 100).toFixed(1)}%`
}

export function BudgetDeltaSummary({ comparison, baselineLabel, candidateLabel }: BudgetDeltaSummaryProps) {
  const gradeDiffers = comparison.baseline_decision_grade !== comparison.candidate_decision_grade
  const optDiffers =
    comparison.baseline_optimization.optimization_status !==
    comparison.candidate_optimization.optimization_status

  return (
    <section className="card" aria-labelledby="delta-title">
      <h3 id="delta-title">실행 비교</h3>
      <p className="result-context">
        기준 <strong>{baselineLabel}</strong> → 변경 <strong>{candidateLabel}</strong>
      </p>

      <div className="summary-badges">
        <AssumptionBadge
          tone={gradeDiffers ? 'warn' : 'info'}
          label={`근거 등급: ${comparison.baseline_decision_grade} → ${comparison.candidate_decision_grade}`}
        />
        <AssumptionBadge
          tone={optDiffers ? 'warn' : 'info'}
          label={`최적화: ${comparison.baseline_optimization.optimization_status} → ${comparison.candidate_optimization.optimization_status}`}
        />
      </div>
      {optDiffers ? (
        <p className="hint hint--warn" role="status">
          두 실행의 최적화 등급이 다릅니다(예: EXACT vs APPROXIMATE). 근사 결과와의 차이는 전역 최적
          기준의 차이일 수 있으므로 그대로 비교하지 마세요.
        </p>
      ) : null}

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">지표</th>
              <th scope="col">기준</th>
              <th scope="col">변경</th>
              <th scope="col">차이</th>
              <th scope="col">비율(변경/기준)</th>
              <th scope="col">비교</th>
            </tr>
          </thead>
          <tbody>
            {comparison.metrics.map((m, i) => {
              const label = m.station_key || m.payload_key ? ` (${m.station_key ?? m.payload_key})` : ''
              return (
                <tr key={`${m.metric}-${i}`}>
                  <td className="mono">
                    {m.metric}
                    {label}
                  </td>
                  <td>{fmtValue(m.baseline, m.unit)}</td>
                  <td>{fmtValue(m.candidate, m.unit)}</td>
                  <td>{m.comparable ? fmtValue(m.absolute_delta, m.unit) : '—'}</td>
                  <td>{fmtRatio(m)}</td>
                  <td>
                    {m.comparable ? (
                      '비교 가능'
                    ) : (
                      <span className="hint">
                        비교 불가: {m.reason_codes.map((r) => r.code).join(', ') || '사유 없음'}
                      </span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="safety-notice">{comparison.safety_notice}</p>
    </section>
  )
}
