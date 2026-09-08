import { useEffect, useState } from 'react'

import { api, ApiError, NetworkError } from '../../shared/api/client'
import { ContractError } from '../../shared/api/parseResult'
import type { DailyBudget } from '../../shared/api/types'
import { formatBytesAdaptive, bytesToExactBytes } from '../../shared/format/units'
import { AssumptionBadge } from '../../shared/ui/AssumptionBadge'

export interface DailyBudgetTableProps {
  /** The run whose already-computed result is re-aggregated per UTC date. */
  runId: string
}

export interface DailyBudgetViewProps {
  budget: DailyBudget | null
  loading: boolean
  error: string | null
}

/**
 * UTC 날짜별 전송 예산 표시(순수 컴포넌트).
 *
 * 로딩·오류·데이터 세 상태를 props로 받아 그린다. 네트워크는 다루지 않아 프롭 기반으로 단순 검증된다
 * (같은 폴더의 PassTable·BudgetSummary와 동일한 패턴). 서버의 읽기 전용 집계(`/daily-budget`)는 이미
 * 계산된 실행 결과를 세션 시작 UTC 날짜 기준으로 재집계한 값이며
 * 분석기간 안에서 접촉이 없는 날은 0(KNOWN_ZERO)으로, 경계의
 * 부분 일자는 명시적으로 표시된다. 결과 계약·hash는 바뀌지 않는다.
 */
export function DailyBudgetView({ budget, loading, error }: DailyBudgetViewProps) {
  return (
    <section className="card" aria-labelledby="daily-budget-title">
      <h3 id="daily-budget-title">UTC 날짜별 전송 예산</h3>

      {loading ? (
        <p className="hint" role="status">
          일별 예산을 불러오는 중…
        </p>
      ) : error ? (
        <p className="hint hint--warn" role="alert">
          일별 예산을 불러오지 못했습니다: {error}
        </p>
      ) : budget ? (
        <DailyBudgetBody budget={budget} />
      ) : null}
    </section>
  )
}

/**
 * `runId`의 이미 계산된 결과를 서버에서 일별로 재집계해 가져와 {@link DailyBudgetView}로 넘기는 얇은
 * 래퍼. 호출부에서 `key={runId}`로 리마운트하면 실행이 바뀔 때 응답 경쟁이 없다. 조회 실패는 표를 비우지
 * 않고 오류 문구로 표시한다.
 */
export function DailyBudgetTable({ runId }: DailyBudgetTableProps) {
  const [budget, setBudget] = useState<DailyBudget | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    void (async () => {
      try {
        const value = await api.getDailyBudget(runId, controller.signal)
        if (cancelled) return
        setBudget(value)
        setLoading(false)
      } catch (err: unknown) {
        if (cancelled) return
        setError(describeDailyBudgetError(err))
        setLoading(false)
      }
    })()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [runId])

  return <DailyBudgetView budget={budget} loading={loading} error={error} />
}

function DailyBudgetBody({ budget }: { budget: DailyBudget }) {
  const computed = budget.calculation_status === 'COMPUTED'
  return (
    <>
      {!computed ? (
        <p className="hint hint--warn" role="status">
          계산 상태 <strong>{budget.calculation_status}</strong> — 완전한 COMPUTED 결과가 아닙니다.
          아래 일별 값은 확정 예산이 아닐 수 있습니다.
        </p>
      ) : null}

      <p className="result-context">{budget.notice}</p>

      <div className="summary-badges">
        <AssumptionBadge tone="assumption" label={`집계 기준: ${budget.aggregation_basis}`} />
        <AssumptionBadge
          tone={budget.sum_preserved ? 'info' : 'warn'}
          label={budget.sum_preserved ? '합계 보존: OK' : '합계 보존: 불일치'}
          title="일별 선택 용량 합이 분석기간 총 선택 용량과 일치하는지"
        />
      </div>

      {budget.days.length === 0 ? (
        <p className="hint">이 분석기간에는 표시할 UTC 날짜가 없습니다.</p>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">UTC 날짜</th>
                <th scope="col">기하 접촉</th>
                <th scope="col">선택 세션</th>
                <th scope="col">선택 용량</th>
                <th scope="col">후보 용량 합</th>
              </tr>
            </thead>
            <tbody>
              {budget.days.map((day) => (
                <tr key={day.utc_date}>
                  <th scope="row" className="mono">
                    {day.utc_date}
                    {day.is_partial ? (
                      <AssumptionBadge
                        tone="warn"
                        label="부분 일자"
                        title="분석기간 경계라 하루 전체가 아닙니다"
                      />
                    ) : null}
                  </th>
                  <td>{day.geometric_contact_count}</td>
                  <td>{day.scheduled_session_count}</td>
                  <td title={bytesToExactBytes(day.scheduled_capacity_bytes)}>{formatBytesAdaptive(day.scheduled_capacity_bytes)}</td>
                  <td title={bytesToExactBytes(day.candidate_capacity_sum_bytes)}>{formatBytesAdaptive(day.candidate_capacity_sum_bytes)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row">합계 (일별 합)</th>
                <td>—</td>
                <td>—</td>
                <td title={bytesToExactBytes(budget.period_scheduled_capacity_from_days_bytes)}>{formatBytesAdaptive(budget.period_scheduled_capacity_from_days_bytes)}</td>
                <td>—</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </>
  )
}

function describeDailyBudgetError(err: unknown): string {
  if (err instanceof ApiError) return `[${err.code}] ${err.message}`
  if (err instanceof NetworkError) return err.message
  if (err instanceof ContractError) return err.message
  if (err instanceof Error) return err.message
  return '알 수 없는 오류'
}
