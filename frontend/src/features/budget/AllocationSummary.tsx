import type { RunResult } from '../../shared/api/types'
import { bytesMetric } from './bytesMetric'

export interface AllocationSummaryProps {
  result: RunResult
}

/** Planned allocation totals for the model-output cart (QUEUE_AWARE). */
export function AllocationSummary({ result }: AllocationSummaryProps) {
  const m = result.metrics
  const mode = result.analysis_mode
  if (mode === 'NETWORK_ONLY') {
    return (
      <section className="card" aria-labelledby="alloc-title">
        <h3 id="alloc-title">출력 할당 요약</h3>
        <p className="hint">NETWORK_ONLY 실행에는 출력 할당 계층이 없습니다 (접촉·용량만 계산).</p>
      </section>
    )
  }
  return (
    <section className="card" aria-labelledby="alloc-title">
      <h3 id="alloc-title">출력 할당 요약 (계획상)</h3>
      <dl className="metric-grid">
        <div className="metric metric--strong">
          <dt>계획 배치 데이터</dt>
          <dd>
            <span className="metric__value">{bytesMetric(m.payload_allocated_bytes, mode)}</span>
            <span className="metric__note">전송 계획상 배치된 논리 바이트</span>
          </dd>
        </div>
        <div className="metric">
          <dt>남은 대기 데이터</dt>
          <dd>
            <span className="metric__value">{bytesMetric(m.payload_remaining_bytes, mode)}</span>
            <span className="metric__note">분석기간 종료 시 미전송 잔여</span>
          </dd>
        </div>
        <div className="metric">
          <dt>미사용 선택 용량</dt>
          <dd>
            <span className="metric__value">
              {bytesMetric(m.stranded_capacity_bytes, mode, '출력 계층 없음')}
            </span>
            <span className="metric__note">선택 세션 중 배치에 쓰이지 못한 용량</span>
          </dd>
        </div>
      </dl>
    </section>
  )
}
