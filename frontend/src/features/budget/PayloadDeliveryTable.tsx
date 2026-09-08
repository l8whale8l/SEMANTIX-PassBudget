import type { PayloadProgress, RunResult } from '../../shared/api/types'
import { formatBytesAdaptive, bytesToExactBytes } from '../../shared/format/units'
import { formatUtc } from '../../shared/format/time'
import { AssumptionBadge } from '../../shared/ui/AssumptionBadge'

export interface PayloadDeliveryTableProps {
  result: RunResult
}

const STATE_LABEL: Record<string, string> = {
  COMPLETED: '계획상 완료',
  PARTIAL: '부분전송',
  DEFERRED: '미전송',
  NOT_STARTED: '미시작 (전송 없음)',
  BLOCKED: '차단',
}

function stateTone(state: string): 'info' | 'warn' {
  return state === 'COMPLETED' ? 'info' : 'warn'
}

/** Per-output planned delivery with reason codes (the backend's plan, not a real receipt). */
export function PayloadDeliveryTable({ result }: PayloadDeliveryTableProps) {
  if (result.analysis_mode === 'NETWORK_ONLY') return null
  const rows: PayloadProgress[] = result.payload_progress
  return (
    <section className="card" aria-labelledby="delivery-title">
      <h3 id="delivery-title">모델 출력 전송 결과 (계획상)</h3>
      <p className="hint">
        “계획상” 상태이며 실제 지상 수신 완료를 뜻하지 않습니다. 서비스 등급·마감·우선순위는 백엔드
        큐 comparator(DEADLINE_SEVERITY_CORE_V1)에 따라 결정됩니다.
      </p>
      {rows.length === 0 ? (
        <p className="hint">표시할 출력물이 없습니다.</p>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">출력물</th>
                <th scope="col">전송 크기</th>
                <th scope="col">할당</th>
                <th scope="col">잔여</th>
                <th scope="col">상태</th>
                <th scope="col">사유</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.payload_key}>
                  <td className="mono">{p.payload_key}</td>
                  <td title={bytesToExactBytes(p.logical_size_bytes)}>{formatBytesAdaptive(p.logical_size_bytes)}</td>
                  <td title={bytesToExactBytes(p.allocated_bytes)}>{formatBytesAdaptive(p.allocated_bytes)}</td>
                  <td title={bytesToExactBytes(p.remaining_bytes)}>{formatBytesAdaptive(p.remaining_bytes)}</td>
                  <td>
                    <AssumptionBadge tone={stateTone(p.state)} label={STATE_LABEL[p.state] ?? p.state} />
                    {p.state === 'PARTIAL' && p.partial_transfer_end_at ? (
                      <div className="hint">~ {formatUtc(p.partial_transfer_end_at)}</div>
                    ) : null}
                  </td>
                  <td className="reason-cell">
                    {p.reason_codes.map((r) => r.code).join(', ') || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
