import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DependencyPanel } from './DependencyPanel'
import { createPayloadForm, type DependencyForm, type PayloadForm } from '../scenario/draft'

function payload(key: string): PayloadForm {
  return createPayloadForm({
    stableKey: key,
    displayName: key,
    logicalSizeBytes: 100,
    readyAt: '2026-09-03T00:00:00Z',
    queueSequence: 1,
    sizeSource: 't',
  })
}

const dep = (id: string, pred: string, succ: string): DependencyForm => ({
  editId: id,
  predecessorKey: pred,
  successorKey: succ,
  kind: 'SEND_AFTER',
})

describe('DependencyPanel', () => {
  it('lists dependencies and removes one', async () => {
    const onRemove = vi.fn()
    render(
      <DependencyPanel
        dependencies={[dep('d1', 'A', 'B')]}
        payloads={[payload('A'), payload('B')]}
        onAdd={() => {}}
        onRemove={onRemove}
      />,
    )
    expect(screen.getByText(/A → B/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '제거' }))
    expect(onRemove).toHaveBeenCalledWith('d1')
  })

  it('adds a dependency between two chosen payloads', async () => {
    const onAdd = vi.fn()
    render(
      <DependencyPanel
        dependencies={[]}
        payloads={[payload('A'), payload('B')]}
        onAdd={onAdd}
        onRemove={() => {}}
      />,
    )
    await userEvent.selectOptions(screen.getByLabelText(/predecessor/), 'A')
    await userEvent.selectOptions(screen.getByLabelText(/successor/), 'B')
    await userEvent.click(screen.getByRole('button', { name: '의존성 추가' }))
    expect(onAdd).toHaveBeenCalledWith('A', 'B')
  })

  it('needs at least two payloads to add a dependency', () => {
    render(
      <DependencyPanel dependencies={[]} payloads={[payload('A')]} onAdd={() => {}} onRemove={() => {}} />,
    )
    expect(screen.getByText(/두 개 이상 필요/)).toBeInTheDocument()
  })
})
