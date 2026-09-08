import type { RunResult, RunResultsEnvelope } from '../../shared/api/types'
import type { SubmittedContext } from '../scenario/useRunScenario'
import { AssumptionBadge } from '../../shared/ui/AssumptionBadge'
import { formatUtc } from '../../shared/format/time'
import { formatBytesAdaptive, microsToHms, microsToSecondsDisplay } from '../../shared/format/units'
import { analysisModeLabel } from '../../shared/format/labels'
import { bytesMetric } from './bytesMetric'

export interface BudgetSummaryProps {
  envelope: RunResultsEnvelope
  /** The input conditions at submit time — shown so the result is never labelled with the current,
   *  possibly edited, draft (correction 4). */
  context: SubmittedContext
}

export function BudgetSummary({ envelope, context }: BudgetSummaryProps) {
  const result: RunResult = envelope.result
  const m = result.metrics
  const opt = result.optimization
  const mode = result.analysis_mode
  const computed = result.calculation_status === 'COMPUTED'
  return (
    <section className="card" aria-labelledby="budget-summary-title">
      <h3 id="budget-summary-title">전송 예산 요약</h3>

      {!computed ? (
        <p className="hint hint--warn" role="status">
          계산 상태 <strong>{result.calculation_status}</strong> — 완전한 COMPUTED 결과가 아닙니다.
          아래 값은 부분/차단 상태일 수 있습니다. (HTTP 성공과 분석 성공은 다릅니다.)
        </p>
      ) : null}

      <p className="result-context">
        이 결과의 입력 조건 — 모드 <strong title={mode}>{analysisModeLabel(mode)}</strong> · 기간{' '}
        {formatUtc(context.windowStart)} → {formatUtc(context.windowEnd)} · 활성 지상국{' '}
        {context.activeStationKeys.length}곳(
        {context.activeStationKeys.join(', ') || '없음'})
      </p>

      <div className="summary-badges">
        <AssumptionBadge tone="assumption" label={`근거 등급: ${result.decision_grade}`} />
        <AssumptionBadge tone={computed ? 'info' : 'warn'} label={`계산 상태: ${result.calculation_status}`} />
        <AssumptionBadge tone="info" label={`접촉 출처: ${result.contact_source}`} />
        <AssumptionBadge
          tone={opt.optimization_status === 'EXACT' ? 'info' : 'warn'}
          label={
            opt.optimization_status === 'EXACT' && opt.globally_optimal
              ? '설정된 목적함수·가정 안에서 최적 (EXACT)'
              : `${opt.optimization_status} · 전역 최적 증명 안 됨`
          }
        />
      </div>

      <dl className="metric-grid">
        <Metric term="기하 접촉 기회" value={String(m.geometric_contact_count)} note="선택 세션 수와 다름" />
        <Metric
          term="선택 세션 수"
          value={String(m.scheduled_session_count)}
          note="실제 RF 수신 횟수 아님"
        />
        <Metric
          term="분석기간 전송 예산"
          value={formatBytesAdaptive(m.scheduled_unique_capacity_bytes)}
          strong
          note="충돌 해결 후 용량 (기본 KPI). 분석기간 총량이며 하루당 값이 아님"
        />
        <Metric
          term="후보 용량 합"
          value={formatBytesAdaptive(m.candidate_capacity_sum_bytes)}
          note="겹침 포함 가능 — 예산으로 사용 금지"
        />
        <Metric
          term="선택 접촉시간"
          value={`${microsToSecondsDisplay(m.scheduled_session_duration_us)} s`}
          note="기하 접촉 합계와 구분"
        />
        <Metric
          term="최대 통신 공백 (INTERNAL)"
          value={m.scheduled_session_gap.max_us === null ? '해당 없음' : microsToHms(m.scheduled_session_gap.max_us)}
          note="하루 전체 통신 불가시간으로 해석 금지"
        />
        <Metric
          term="출력 할당"
          value={bytesMetric(m.payload_allocated_bytes, mode, '출력 계층 없음')}
        />
        <Metric
          term="출력 잔여"
          value={bytesMetric(m.payload_remaining_bytes, mode, '출력 계층 없음')}
        />
        <Metric
          term="미사용 선택 용량"
          value={bytesMetric(m.stranded_capacity_bytes, mode, '출력 계층 없음')}
          note="다른 byte 계층과 임의로 빼서 계산하지 않음"
        />
      </dl>

      <table className="mini-table">
        <caption>지상국별 기하 접촉</caption>
        <thead>
          <tr>
            <th scope="col">지상국</th>
            <th scope="col">접촉 수</th>
            <th scope="col">후보 용량 합</th>
            <th scope="col">근거 등급</th>
          </tr>
        </thead>
        <tbody>
          {m.stations.map((s) => (
            <tr key={s.station_key}>
              <td className="mono">{s.station_key}</td>
              <td>{s.geometric_contact_count}</td>
              <td>{bytesMetric(s.candidate_capacity_sum_bytes, mode)}</td>
              <td>{s.decision_grade}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="hashline mono">
        input_snapshot_hash: {envelope.input_snapshot_hash.slice(0, 16)}… ·
        result_content_hash: {envelope.result_content_hash.slice(0, 16)}…
      </p>
    </section>
  )
}

function Metric({
  term,
  value,
  note,
  strong,
}: {
  term: string
  value: string
  note?: string
  strong?: boolean
}) {
  return (
    <div className={`metric${strong ? ' metric--strong' : ''}`}>
      <dt>{term}</dt>
      <dd>
        <span className="metric__value">{value}</span>
        {note ? <span className="metric__note">{note}</span> : null}
      </dd>
    </div>
  )
}
