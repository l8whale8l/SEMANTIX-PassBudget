import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ScenarioLibrary } from './ScenarioLibrary'
import { ORB_PRESET } from '../scenario/presets'
import { draftFromPreset, type ScenarioDraft } from '../scenario/draft'
import { api, ApiError } from '../../shared/api/client'

vi.mock('../../shared/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../shared/api/client')>()
  return {
    ...actual,
    api: {
      createScenario: vi.fn(),
      publishScenarioRevision: vi.fn(),
      createSnapshot: vi.fn(),
      createScenarioRevision: vi.fn(),
      getScenario: vi.fn(),
      getRevisionContent: vi.fn(),
      cloneScenarioRevision: vi.fn(),
    },
  }
})

const m = api as unknown as Record<string, Mock>

beforeEach(() => {
  localStorage.clear()
  Object.values(m).forEach((fn) => fn.mockReset())
})
afterEach(() => vi.clearAllMocks())

function renderLib(onLoad: (d: ScenarioDraft) => void = () => {}, mode: 'open' | 'save' = 'open') {
  return render(
    <ScenarioLibrary draft={draftFromPreset(ORB_PRESET)} unsaved={false} onLoadDraft={onLoad} mode={mode} />,
  )
}

describe('ScenarioLibrary save (FE-16)', () => {
  it('creates → publishes → snapshots and stores only a pointer, then rebases the draft', async () => {
    m.createScenario.mockResolvedValue({
      scenario_id: 's1',
      revisions: [{ revision_id: 'r1', revision_no: 1 }],
    })
    m.publishScenarioRevision.mockResolvedValue({ revision_id: 'r1', revision_no: 1 })
    m.createSnapshot.mockResolvedValue({ snapshot_id: 'snap1' })
    const onLoad = vi.fn()
    renderLib(onLoad, 'save')

    await userEvent.click(screen.getByRole('button', { name: '새 시나리오로 저장' }))

    await waitFor(() => expect(m.createSnapshot).toHaveBeenCalledWith('r1'))
    expect(m.createScenario).toHaveBeenCalledTimes(1)
    expect(m.publishScenarioRevision).toHaveBeenCalledWith('r1')
    // The content sent carries the fixture body, not raw text.
    const sentContent = m.createScenario.mock.calls[0][0].content
    expect(sentContent.fixture_id).toBe('PB-GOLDEN-ORB-01')
    // localStorage holds only a pointer (id + name), never the content.
    const stored = JSON.parse(localStorage.getItem('passbudget.savedScenarios.v1') ?? '[]')
    expect(stored[0].scenarioId).toBe('s1')
    expect(JSON.stringify(stored)).not.toContain('stations')
    // The draft is rebased onto the saved scenario (so later saves become revisions).
    await waitFor(() => expect(onLoad).toHaveBeenCalled())
    expect(onLoad.mock.calls[0][0].savedScenarioId).toBe('s1')
  })
})

describe('ScenarioLibrary load (FE-16)', () => {
  it('re-reads the saved content from the server and restores an editable draft', async () => {
    localStorage.setItem(
      'passbudget.savedScenarios.v1',
      JSON.stringify([{ scenarioId: 's1', stableKey: 'k', name: 'Saved One', savedAt: 'x' }]),
    )
    m.getScenario.mockResolvedValue({ scenario_id: 's1', name: 'Saved One', current_revision_id: 'r9' })
    m.getRevisionContent.mockResolvedValue({ content: ORB_PRESET.content })
    const onLoad = vi.fn()
    renderLib(onLoad)

    await userEvent.click(screen.getByRole('button', { name: '불러오기' }))

    await waitFor(() => expect(m.getRevisionContent).toHaveBeenCalledWith('r9'))
    expect(m.getScenario).toHaveBeenCalledWith('s1')
    const loaded: ScenarioDraft = onLoad.mock.calls[0][0]
    expect(loaded.savedScenarioId).toBe('s1')
    expect(loaded.presetIsPublicFixture).toBe(false)
    expect(loaded.stations).toHaveLength(2)
  })

  it('loads a DRAFT-only (cloned) scenario via its newest revision (CLOSE-04)', async () => {
    localStorage.setItem(
      'passbudget.savedScenarios.v1',
      JSON.stringify([{ scenarioId: 'clone-1', stableKey: 'k', name: 'A clone', savedAt: 'x' }]),
    )
    // A freshly cloned scenario has no published current_revision_id, only a DRAFT revision.
    m.getScenario.mockResolvedValue({
      scenario_id: 'clone-1',
      name: 'A clone',
      current_revision_id: null,
      revisions: [{ revision_id: 'draft-rev', revision_no: 1, lifecycle_status: 'DRAFT' }],
    })
    m.getRevisionContent.mockResolvedValue({ content: ORB_PRESET.content })
    const onLoad = vi.fn()
    renderLib(onLoad)

    await userEvent.click(screen.getByRole('button', { name: '불러오기' }))

    // It reads the DRAFT revision's content (not the missing current pointer) and loads it.
    await waitFor(() => expect(m.getRevisionContent).toHaveBeenCalledWith('draft-rev'))
    expect(onLoad).toHaveBeenCalled()
    expect(await screen.findByText(/초안 리비전/)).toBeInTheDocument()
  })
})

describe('ScenarioLibrary clone (FE-17)', () => {
  it('clones from the current revision and adds a new pointer, without loading over the draft', async () => {
    localStorage.setItem(
      'passbudget.savedScenarios.v1',
      JSON.stringify([{ scenarioId: 's1', stableKey: 'k', name: 'Orig', savedAt: 'x' }]),
    )
    m.getScenario.mockResolvedValue({ scenario_id: 's1', name: 'Orig', current_revision_id: 'r1' })
    m.cloneScenarioRevision.mockResolvedValue({
      scenario_id: 's2',
      stable_key: 'k2',
      name: 'Orig (사본)',
    })
    const onLoad = vi.fn()
    renderLib(onLoad)

    await userEvent.click(screen.getByRole('button', { name: '복제' }))

    await waitFor(() => expect(m.cloneScenarioRevision).toHaveBeenCalled())
    expect(m.cloneScenarioRevision.mock.calls[0][0]).toBe('r1')
    const stored = JSON.parse(localStorage.getItem('passbudget.savedScenarios.v1') ?? '[]')
    expect(stored.some((p: { scenarioId: string }) => p.scenarioId === 's2')).toBe(true)
    expect(onLoad).not.toHaveBeenCalled() // clone does not overwrite the working draft
  })
})

describe('ScenarioLibrary stale pointer after a backend restart (FE-16/FE-20)', () => {
  it('explains a 404 as a restarted/absent scenario and lets the user remove the pointer', async () => {
    localStorage.setItem(
      'passbudget.savedScenarios.v1',
      JSON.stringify([{ scenarioId: 'gone', stableKey: 'k', name: 'Old', savedAt: 'x' }]),
    )
    // The in-memory catalog lost this scenario when the backend restarted.
    m.getScenario.mockRejectedValue(
      new ApiError(404, 'SCENARIO_NOT_FOUND', 'No scenario exists for this identifier.'),
    )
    renderLib()

    await act(async () => {
      await userEvent.click(screen.getByRole('button', { name: '불러오기' }))
    })
    expect(await screen.findByText(/백엔드가 재시작/)).toBeInTheDocument()

    // Removing the stale pointer is a local-only action (server data untouched).
    await userEvent.click(screen.getByRole('button', { name: '제거' }))
    expect(JSON.parse(localStorage.getItem('passbudget.savedScenarios.v1') ?? '[]')).toHaveLength(0)
  })
})

describe('ScenarioLibrary error handling (FE-20)', () => {
  it('shows a server error on save without losing the draft', async () => {
    m.createScenario.mockRejectedValue(
      new ApiError(422, 'DUPLICATE_STABLE_KEY', 'A scenario with this stable key already exists.'),
    )
    const onLoad = vi.fn()
    renderLib(onLoad, 'save')

    await act(async () => {
      await userEvent.click(screen.getByRole('button', { name: '새 시나리오로 저장' }))
    })

    expect(await screen.findByText(/DUPLICATE_STABLE_KEY/)).toBeInTheDocument()
    expect(onLoad).not.toHaveBeenCalled()
    expect(m.publishScenarioRevision).not.toHaveBeenCalled()
  })
})
