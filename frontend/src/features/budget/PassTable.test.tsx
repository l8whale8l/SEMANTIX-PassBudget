import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { PassTable } from './PassTable'
import { findScheduledForAccess, keyIdentity } from './passMatch'
import type { RunResult } from '../../shared/api/types'
import orbEnvelope from '../../test/fixtures/orb_results_envelope.json'

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T
const orbResult = () => clone(orbEnvelope).result as unknown as RunResult

describe('keyIdentity / findScheduledForAccess (defect 3)', () => {
  it('extracts the identity after the layer prefix', () => {
    expect(keyIdentity('geometric/ORB-X-905')).toBe('ORB-X-905')
    expect(keyIdentity('no-prefix')).toBe('no-prefix')
  })

  it('matches the scheduled session exactly, not by suffix', () => {
    const r = orbResult()
    const access = r.geometric_accesses[0]
    const matched = findScheduledForAccess(r, access.stable_key)
    expect(matched).not.toBeNull()
    expect(keyIdentity(matched!.candidate_stable_key)).toBe(keyIdentity(access.stable_key))
  })

  it('does not false-match a session whose id merely ends with the access id', () => {
    const r = orbResult()
    // Craft an access id that is a strict suffix of an existing scheduled id.
    const realId = keyIdentity(r.scheduled_sessions[0].candidate_stable_key)
    const access = { ...r.geometric_accesses[0], stable_key: `geometric/${realId.slice(1)}` }
    // The shortened id is a suffix of the real one; an endsWith match would wrongly pick it.
    expect(findScheduledForAccess(r, access.stable_key)).toBeNull()
  })
})

describe('PassTable rendering', () => {
  it('shows the 7 golden passes with max elevation', () => {
    render(<PassTable result={orbResult()} selectedPassKey={null} onSelect={() => {}} />)
    expect(screen.getByText('77.081')).toBeInTheDocument()
    expect(screen.getAllByText('상세').length).toBe(7)
  })

  it('shows a no-contact message when there are no accesses', () => {
    const r = orbResult()
    r.geometric_accesses = []
    render(<PassTable result={r} selectedPassKey={null} onSelect={() => {}} />)
    expect(screen.getByText(/기하 접촉 기회가 없습니다/)).toBeInTheDocument()
  })
})
