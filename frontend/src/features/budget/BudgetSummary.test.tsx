import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BudgetSummary } from './BudgetSummary'
import type { RunResultsEnvelope } from '../../shared/api/types'
import type { SubmittedContext } from '../scenario/useRunScenario'
import orbEnvelope from '../../test/fixtures/orb_results_envelope.json'
import netonlyEnvelope from '../../test/fixtures/netonly_results_envelope.json'

const ctx = (mode: string): SubmittedContext => ({
  analysisMode: mode,
  windowStart: '2026-09-03T00:00:00Z',
  windowEnd: '2026-09-04T00:00:00Z',
  activeStationKeys: ['SYN-GS-MIDLAT', 'SYN-GS-EQUATOR'],
})

describe('BudgetSummary', () => {
  it('renders the QUEUE_AWARE budget from the real envelope', () => {
    render(
      <BudgetSummary envelope={orbEnvelope as unknown as RunResultsEnvelope} context={ctx('QUEUE_AWARE')} />,
    )
    // 526,555,476 B -> 526.56 MB, read from the API result (not hard-coded in the component).
    expect(screen.getAllByText(/526\.56 MB/).length).toBeGreaterThan(0)
  })

  it('renders a NETWORK_ONLY result whose stranded/allocation metrics are null, without crashing', () => {
    // Regression for the RangeError: null was passed straight to the byte formatter (correction 2).
    render(
      <BudgetSummary
        envelope={netonlyEnvelope as unknown as RunResultsEnvelope}
        context={ctx('NETWORK_ONLY')}
      />,
    )
    // The unique capacity is still shown; the null metrics read as "not applicable", not 0 or crash.
    // (ORB run in NETWORK_ONLY: same 526.56 MB capacity, but no payload allocation layer.)
    expect(screen.getAllByText(/526\.56 MB/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/해당 없음/).length).toBeGreaterThan(0)
    expect(screen.queryByText(/0\.00 MB/)).not.toBeInTheDocument()
  })

  it('shows the submitted context, not a caller-supplied current draft', () => {
    render(
      <BudgetSummary envelope={orbEnvelope as unknown as RunResultsEnvelope} context={ctx('QUEUE_AWARE')} />,
    )
    expect(screen.getByText(/이 결과의 입력 조건/)).toBeInTheDocument()
    expect(screen.getAllByText(/SYN-GS-MIDLAT/).length).toBeGreaterThan(0)
  })
})
