import type { GeometricAccess, RunResult, ScheduledSession } from '../../shared/api/types'
import { formatUtcClock } from '../../shared/format/time'
import { bytesToMbDisplay } from '../../shared/format/units'
import { AssumptionBadge } from '../../shared/ui/AssumptionBadge'
import { findScheduledForAccess } from './passMatch'

export interface PassTableProps {
  result: RunResult
  selectedPassKey: string | null
  onSelect: (stableKey: string | null) => void
}

/** μdeg -> degrees for display (exact enough for a 6-dp angle). Absent for SYNTHETIC accesses. */
function udegToDeg(udeg: number | null | undefined): string {
  if (udeg == null) return '—'
  return (udeg / 1_000_000).toFixed(3)
}

export function PassTable({ result, selectedPassKey, onSelect }: PassTableProps) {
  const accesses = result.geometric_accesses
  const scheduledByCandidate = new Map<string, ScheduledSession>()
  for (const s of result.scheduled_sessions) {
    scheduledByCandidate.set(s.candidate_stable_key, s)
  }

  if (accesses.length === 0) {
    return (
      <section className="card">
        <h3>패스 표</h3>
        <p className="hint">이 조건에서 기하 접촉 기회가 없습니다 (무접촉).</p>
      </section>
    )
  }

  return (
    <section className="card" aria-labelledby="pass-table-title">
      <h3 id="pass-table-title">패스 표 (기하 접촉)</h3>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">지상국</th>
              <th scope="col">AOS (UTC)</th>
              <th scope="col">LOS (UTC)</th>
              <th scope="col">최대 앙각 (deg)</th>
              <th scope="col">클리핑</th>
              <th scope="col"></th>
            </tr>
          </thead>
          <tbody>
            {accesses.map((access: GeometricAccess) => {
              const selected = access.stable_key === selectedPassKey
              return (
                <tr key={access.stable_key} className={selected ? 'row--selected' : undefined}>
                  <td className="mono">{access.station_key}</td>
                  <td className="mono">{formatUtcClock(access.true_aos)}</td>
                  <td className="mono">{formatUtcClock(access.true_los)}</td>
                  <td>{udegToDeg(access.maximum_elevation_udeg)}</td>
                  <td>
                    {access.clipped_start || access.clipped_end ? (
                      <AssumptionBadge tone="warn" label="clipped" title="분석기간 경계에서 잘림" />
                    ) : (
                      '—'
                    )}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn btn--link"
                      aria-pressed={selected}
                      onClick={() => onSelect(selected ? null : access.stable_key)}
                    >
                      {selected ? '닫기' : '상세'}
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {selectedPassKey ? (
        <PassDetailPanel
          access={accesses.find((a) => a.stable_key === selectedPassKey) ?? null}
          scheduled={findScheduledForAccess(result, selectedPassKey)}
        />
      ) : null}
    </section>
  )
}

function PassDetailPanel({
  access,
  scheduled,
}: {
  access: GeometricAccess | null
  scheduled: ScheduledSession | null
}) {
  if (!access) return null
  return (
    <div className="detail-panel">
      <h4>패스 상세</h4>
      <dl className="detail-grid">
        <dt>stable_key</dt>
        <dd className="mono">{access.stable_key}</dd>
        <dt>최대 앙각 시각</dt>
        <dd className="mono">{access.maximum_elevation_at ?? '—'}</dd>
        <dt>계산 상태 / 등급</dt>
        <dd>
          {access.calculation_status} / {access.decision_grade}
        </dd>
        {scheduled ? (
          <>
            <dt>선택 세션 용량</dt>
            <dd>{bytesToMbDisplay(scheduled.capacity_bytes)} MB</dd>
            <dt>선택 사유</dt>
            <dd>{scheduled.reason_codes.map((r) => r.code).join(', ') || '—'}</dd>
          </>
        ) : (
          <>
            <dt>선택 세션</dt>
            <dd>이 접촉은 선택 세션으로 연결되지 않았습니다.</dd>
          </>
        )}
      </dl>
    </div>
  )
}
