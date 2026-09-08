import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { PayloadCart, PayloadDetail } from './PayloadCart'
import { createPayloadForm, type PayloadForm } from '../scenario/draft'

function form(overrides: Partial<PayloadForm> = {}): PayloadForm {
  return {
    ...createPayloadForm({
      stableKey: 'OUTPUT-1',
      displayName: 'out',
      logicalSizeBytes: 1000,
      readyAt: '2026-09-03T00:00:00Z',
      queueSequence: 1,
      sizeSource: 'test',
    }),
    ...overrides,
  }
}

function renderCart(payloads: PayloadForm[], extra: Partial<ComponentProps<typeof PayloadCart>> = {}) {
  return render(
    <PayloadCart
      payloads={payloads}
      patchPayload={() => {}}
      removePayload={() => {}}
      analysisMode="QUEUE_AWARE"
      referencedKeys={new Set()}
      referencingText={() => ''}
      {...extra}
    />,
  )
}

describe('PayloadCart list', () => {
  it('marks the cart as excluded in NETWORK_ONLY', () => {
    renderCart([form()], { analysisMode: 'NETWORK_ONLY' })
    expect(screen.getByText(/계산 대상에서 제외/)).toBeInTheDocument()
    expect(screen.getByText('실행 제외')).toBeInTheDocument()
  })
})

describe('PayloadCart referenced-payload blocking (defect 2)', () => {
  it('disables delete and names the reference in the row', () => {
    const remove = vi.fn()
    renderCart([form({ stableKey: 'OUTPUT-1' })], {
      removePayload: remove,
      referencedKeys: new Set(['OUTPUT-1']),
      referencingText: () => 'OUTPUT-1 → OUTPUT-2',
    })
    expect(screen.getByRole('button', { name: '제거' })).toBeDisabled()
    expect(screen.getByText(/의존성 참조됨/)).toBeInTheDocument()
  })

  it('allows delete when the payload is not referenced', () => {
    renderCart([form({ stableKey: 'FREE-1' })], { referencedKeys: new Set(['OTHER']) })
    expect(screen.getByRole('button', { name: '제거' })).toBeEnabled()
  })
})

function renderDetail(payload: PayloadForm, extra: Partial<ComponentProps<typeof PayloadDetail>> = {}) {
  return render(
    <PayloadDetail
      payload={payload}
      onPatch={() => {}}
      excluded={false}
      referenced={false}
      referencingText=""
      {...extra}
    />,
  )
}

describe('PayloadDetail (defect 1)', () => {
  it('does not crash when a size string is out of the safe-integer range', () => {
    const p = form({ logicalSizeBytes: '99999999999999999999999', storageSizeBytes: '1a2' })
    expect(() => renderDetail(p)).not.toThrow()
    expect(screen.getAllByText(/정수 바이트/).length).toBeGreaterThan(0)
  })

  it('renders a hostile display name as text, not markup (FE-26)', () => {
    const { container } = renderDetail(form({ displayName: '<img src=x onerror=alert(1)>' }))
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByDisplayValue('<img src=x onerror=alert(1)>')).toBeInTheDocument()
  })

  it('freezes the stable key and surfaces the reference for a referenced payload (defect 2)', () => {
    renderDetail(form({ stableKey: 'OUTPUT-1' }), { referenced: true, referencingText: 'OUTPUT-1 → OUTPUT-2' })
    expect(screen.getByDisplayValue('OUTPUT-1')).toBeDisabled()
    expect(screen.getByText(/OUTPUT-1 → OUTPUT-2/)).toBeInTheDocument()
  })
})
