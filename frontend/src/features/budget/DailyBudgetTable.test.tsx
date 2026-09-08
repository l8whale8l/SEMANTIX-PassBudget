import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { DailyBudgetTable, DailyBudgetView } from './DailyBudgetTable'
import type { DailyBudget } from '../../shared/api/types'
import { api } from '../../shared/api/client'

vi.mock('../../shared/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../shared/api/client')>()
  return { ...actual, api: { getDailyBudget: vi.fn() } }
})
const getDailyBudget = api.getDailyBudget as unknown as Mock

function budget(overrides: Partial<DailyBudget> = {}): DailyBudget {
  return {
    run_id: 'RUN-1',
    analysis_window: { start: '2026-09-03T00:00:00.000000Z', end: '2026-09-05T00:00:00.000000Z' },
    aggregation_basis: 'UTC_DATE_OF_SESSION_START',
    calculation_status: 'COMPUTED',
    period_scheduled_unique_capacity_bytes: 3_000_000,
    period_scheduled_capacity_from_days_bytes: 3_000_000,
    sum_preserved: true,
    days: [
      {
        utc_date: '2026-09-03',
        is_partial: false,
        geometric_contact_count: 2,
        scheduled_session_count: 2,
        scheduled_capacity_bytes: 1_000_000,
        candidate_session_count: 2,
        candidate_capacity_sum_bytes: 1_000_000,
      },
      {
        utc_date: '2026-09-04',
        is_partial: false,
        geometric_contact_count: 3,
        scheduled_session_count: 3,
        scheduled_capacity_bytes: 2_000_000,
        candidate_session_count: 3,
        candidate_capacity_sum_bytes: 2_000_000,
      },
    ],
    notice: '일별 값은 세션을 시작 UTC 날짜에 귀속한 집계입니다.',
    ...overrides,
  }
}

// The rendering is a pure prop-driven component (like PassTable/BudgetSummary), so its states are
// verified synchronously without any promise — no fetch mock, no async race.
describe('DailyBudgetView (F4) rendering', () => {
  it('renders one row per UTC date and names the aggregation basis', () => {
    render(<DailyBudgetView budget={budget()} loading={false} error={null} />)
    expect(screen.getByText('2026-09-03')).toBeInTheDocument()
    expect(screen.getByText('2026-09-04')).toBeInTheDocument()
    // A start-day attribution is never silent: the basis is shown to the reader.
    expect(screen.getByText(/UTC_DATE_OF_SESSION_START/)).toBeInTheDocument()
  })

  it('flags a partial boundary day and marks a broken sum invariant', () => {
    render(
      <DailyBudgetView
        budget={budget({
          sum_preserved: false,
          days: [
            {
              utc_date: '2026-09-03',
              is_partial: true,
              geometric_contact_count: 1,
              scheduled_session_count: 1,
              scheduled_capacity_bytes: 500_000,
              candidate_session_count: 1,
              candidate_capacity_sum_bytes: 500_000,
            },
          ],
        })}
        loading={false}
        error={null}
      />,
    )
    expect(screen.getByText('부분 일자')).toBeInTheDocument()
    expect(screen.getByText('합계 보존: 불일치')).toBeInTheDocument()
  })

  it('shows a non-COMPUTED status as a warning, not a confirmed budget', () => {
    render(
      <DailyBudgetView budget={budget({ calculation_status: 'BLOCKED' })} loading={false} error={null} />,
    )
    expect(screen.getByText(/완전한 COMPUTED 결과가 아닙니다/)).toBeInTheDocument()
  })

  it('shows a loading state before data arrives', () => {
    render(<DailyBudgetView budget={null} loading={true} error={null} />)
    expect(screen.getByRole('status')).toHaveTextContent(/불러오는 중/)
  })

  it('surfaces a fetch error instead of a blank table', () => {
    render(<DailyBudgetView budget={null} loading={false} error="[SERVER_ERROR] boom" />)
    expect(screen.getByRole('alert')).toHaveTextContent(/일별 예산을 불러오지 못했습니다/)
    expect(screen.getByRole('alert')).toHaveTextContent(/boom/)
  })
})

describe('DailyBudgetTable (F4) fetch wrapper', () => {
  beforeEach(() => getDailyBudget.mockReset())
  afterEach(() => vi.clearAllMocks())

  it('fetches the per-date budget by run id and renders it', async () => {
    getDailyBudget.mockResolvedValue(budget())
    render(<DailyBudgetTable runId="RUN-1" />)

    await waitFor(() => expect(getDailyBudget).toHaveBeenCalledWith('RUN-1', expect.anything()))
    expect(await screen.findByText('2026-09-03')).toBeInTheDocument()
  })
})
