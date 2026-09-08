import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { PayloadDeliveryTable } from './PayloadDeliveryTable'
import { AllocationSummary } from './AllocationSummary'
import type { RunResult } from '../../shared/api/types'
import orbEnvelope from '../../test/fixtures/orb_results_envelope.json'

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T
const orbResult = () => clone(orbEnvelope).result as unknown as RunResult

describe('PayloadDeliveryTable (FE-14)', () => {
  it('shows planned completion / partial states from the API result', () => {
    render(<PayloadDeliveryTable result={orbResult()} />)
    // Golden: wildfire & fighter COMPLETED, ship PARTIAL.
    expect(screen.getAllByText('계획상 완료').length).toBe(2)
    expect(screen.getByText('부분전송')).toBeInTheDocument()
    expect(screen.getByText(/SHIP-DETECT/)).toBeInTheDocument()
  })

  it('renders a hostile payload key as text, not as HTML (FE-26)', () => {
    const r = orbResult()
    r.payload_progress[0].payload_key = '<img src=x onerror=alert(1)>'
    const { container } = render(<PayloadDeliveryTable result={r} />)
    // The string is shown verbatim and no <img> element is injected.
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(container.querySelector('img')).toBeNull()
  })

  it('renders nothing in NETWORK_ONLY (payloads excluded)', () => {
    const r = orbResult()
    r.analysis_mode = 'NETWORK_ONLY'
    const { container } = render(<PayloadDeliveryTable result={r} />)
    expect(container.firstChild).toBeNull()
  })
})

describe('AllocationSummary', () => {
  it('shows planned allocation totals for QUEUE_AWARE', () => {
    render(<AllocationSummary result={orbResult()} />)
    expect(screen.getByText(/계획 배치 데이터/)).toBeInTheDocument()
    expect(screen.getByText(/522\.00 MB/)).toBeInTheDocument() // payload_allocated_bytes
    expect(screen.getByText(/158\.00 MB/)).toBeInTheDocument() // payload_remaining_bytes
  })

  it('states that NETWORK_ONLY has no allocation layer', () => {
    const r = orbResult()
    r.analysis_mode = 'NETWORK_ONLY'
    render(<AllocationSummary result={r} />)
    expect(screen.getByText(/출력 할당 계층이 없습니다/)).toBeInTheDocument()
  })
})
