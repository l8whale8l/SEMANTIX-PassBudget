import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { GlobeContact } from './model'
import { PassWindowTimeline } from './PassWindowTimeline'

const DAY_START = Date.parse('2026-09-03T00:00:00Z')
const DAY_END = Date.parse('2026-09-04T00:00:00Z')
const CONTACTS: GlobeContact[] = [
  {
    stableKey: 'pass/a', stationKey: 'SYN-GS',
    aosIso: '2026-09-03T06:00:00Z', losIso: '2026-09-03T06:10:00Z',
    aosMs: Date.parse('2026-09-03T06:00:00Z'), losMs: Date.parse('2026-09-03T06:10:00Z'),
    scheduled: true, maximumElevationDeg: 35,
  },
  {
    stableKey: 'pass/b', stationKey: 'KAU-GS',
    aosIso: '2026-09-03T12:00:00Z', losIso: '2026-09-03T12:08:00Z',
    aosMs: Date.parse('2026-09-03T12:00:00Z'), losMs: Date.parse('2026-09-03T12:08:00Z'),
    scheduled: false, maximumElevationDeg: 20,
  },
]

describe('PassWindowTimeline', () => {
  it('shows every AOS–LOS interval as readable UTC text', () => {
    render(
      <PassWindowTimeline contacts={CONTACTS} windowStartMs={DAY_START} windowEndMs={DAY_END}
        currentMs={DAY_START} selectedPassKey={null} onSelect={() => undefined} />,
    )
    expect(screen.getByRole('button', { name: 'P1 06:00:00–06:10:00' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'P2 12:00:00–12:08:00' })).toBeInTheDocument()
    expect(screen.getByText('2회 · AOS → LOS (UTC)')).toBeInTheDocument()
  })

  it('selects a pass from its readable time chip', () => {
    const onSelect = vi.fn()
    render(
      <PassWindowTimeline contacts={CONTACTS} windowStartMs={DAY_START} windowEndMs={DAY_END}
        currentMs={DAY_START} selectedPassKey="pass/b" onSelect={onSelect} />,
    )
    expect(screen.getByText('KAU-GS · 12:00:00–12:08:00 UTC')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'P1 06:00:00–06:10:00' }))
    expect(onSelect).toHaveBeenCalledWith('pass/a')
  })
})
