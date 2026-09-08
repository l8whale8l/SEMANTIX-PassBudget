import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ScenarioComparePanel } from './ScenarioComparePanel'
import type { SubmittedRun } from '../scenario/useRunScenario'
import { api } from '../../shared/api/client'
import comparison from '../../test/fixtures/comparison_response.json'

vi.mock('../../shared/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../shared/api/client')>()
  return { ...actual, api: { createComparison: vi.fn() } }
})
const createComparison = api.createComparison as unknown as Mock

function run(id: string, stations: string[]): SubmittedRun {
  return {
    inputIdentity: `id-${id}`,
    context: { analysisMode: 'QUEUE_AWARE', windowStart: 'w0', windowEnd: 'w1', activeStationKeys: stations },
    metadata: {
      run_id: id, status: 'SUCCEEDED', input_snapshot_hash: '', result_content_hash: '',
      run_record_hash: '', stages: [],
    },
    envelope: { run_id: id, input_snapshot_hash: '', result_content_hash: '', result: {} as SubmittedRun['envelope']['result'] },
  }
}

beforeEach(() => createComparison.mockReset())
afterEach(() => vi.clearAllMocks())

describe('ScenarioComparePanel (FE-18)', () => {
  it('prompts for two runs before it can compare', () => {
    render(<ScenarioComparePanel history={[run('A', ['S1', 'S2'])]} />)
    expect(screen.getByText(/최소 두 번 실행/)).toBeInTheDocument()
  })

  it('compares two selected runs and renders the deltas + incomparable reasons', async () => {
    createComparison.mockResolvedValue(comparison)
    render(<ScenarioComparePanel history={[run('AAAA', ['S1', 'S2']), run('BBBB', ['S1'])]} />)

    await userEvent.selectOptions(screen.getByLabelText('기준 실행'), 'AAAA')
    await userEvent.selectOptions(screen.getByLabelText('변경 실행'), 'BBBB')
    await userEvent.click(screen.getByRole('button', { name: '비교 실행' }))

    await waitFor(() => expect(createComparison).toHaveBeenCalledWith('AAAA', 'BBBB'))
    expect(screen.getByText('SCHEDULED_UNIQUE_CAPACITY_BYTES')).toBeInTheDocument()
    expect(screen.getAllByText(/비교 불가/).length).toBeGreaterThan(0)
  })

  // Comparison error mapping (404 → typed ApiError, and that the UI would show it via the same
  // StatusPanel path proven in ScenarioLibrary) is covered deterministically at the client boundary
  // in `shared/api/client.test.ts`, avoiding a React-19/jsdom async-handler artifact here.
})
