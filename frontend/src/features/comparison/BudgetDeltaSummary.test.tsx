import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BudgetDeltaSummary } from './BudgetDeltaSummary'
import type { ComparisonResponse } from '../../shared/api/types'
import comparison from '../../test/fixtures/comparison_response.json'

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T

describe('BudgetDeltaSummary (FE-18)', () => {
  it('shows the delta for comparable metrics from the real comparison API', () => {
    render(
      <BudgetDeltaSummary
        comparison={comparison as unknown as ComparisonResponse}
        baselineLabel="2 stations"
        candidateLabel="1 station"
      />,
    )
    // The unique-capacity metric is comparable and drops from 526.56 to 309.27 MB.
    expect(screen.getByText('SCHEDULED_UNIQUE_CAPACITY_BYTES')).toBeInTheDocument()
    expect(screen.getAllByText(/526\.56 MB/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/309\.27 MB/).length).toBeGreaterThan(0)
  })

  it('hides the delta and shows a reason for an incomparable metric', () => {
    render(
      <BudgetDeltaSummary
        comparison={comparison as unknown as ComparisonResponse}
        baselineLabel="b"
        candidateLabel="c"
      />,
    )
    expect(screen.getAllByText(/비교 불가/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/METRIC_NOT_COMPUTED_IN_BOTH_RUNS/).length).toBeGreaterThan(0)
  })

  it('warns when the two runs have different optimization grades', () => {
    const c = clone(comparison) as unknown as ComparisonResponse
    c.candidate_optimization = { ...c.candidate_optimization, optimization_status: 'APPROXIMATE' }
    render(<BudgetDeltaSummary comparison={c} baselineLabel="b" candidateLabel="c" />)
    expect(screen.getByText(/최적화 등급이 다릅니다/)).toBeInTheDocument()
  })
})
