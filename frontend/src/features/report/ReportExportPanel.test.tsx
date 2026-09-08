import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ReportExportPanel } from './ReportExportPanel'
import type { SubmittedRun } from '../scenario/useRunScenario'
import { api } from '../../shared/api/client'

vi.mock('../../shared/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../shared/api/client')>()
  return { ...actual, api: { getReportText: vi.fn() } }
})
const getReportText = api.getReportText as unknown as Mock

function run(id: string): SubmittedRun {
  return {
    inputIdentity: `id-${id}`,
    context: { analysisMode: 'QUEUE_AWARE', windowStart: 'w0', windowEnd: 'w1', activeStationKeys: ['S1'] },
    metadata: {
      run_id: id,
      status: 'SUCCEEDED',
      input_snapshot_hash: `snap-${id}`,
      result_content_hash: `res-${id}`,
      run_record_hash: `rec-${id}`,
      stages: [],
    },
    envelope: {
      run_id: id,
      input_snapshot_hash: `snap-${id}`,
      result_content_hash: `res-${id}`,
      result: {} as SubmittedRun['envelope']['result'],
    },
  }
}

beforeEach(() => getReportText.mockReset())
afterEach(() => vi.clearAllMocks())

describe('ReportExportPanel A/B switching (FE-19)', () => {
  it('lets the user choose which run (A or B) to report, not only the latest', async () => {
    // history is newest-first: B is latest, A is the earlier run.
    const history = [run('BBBBBBBB'), run('AAAAAAAA')]
    getReportText.mockImplementation((id: string) => Promise.resolve(`REPORT for ${id}`))
    render(<ReportExportPanel history={history} />)

    // Switch the report target to the earlier run A.
    const selector = screen.getByLabelText(/보고서 대상 실행/)
    await userEvent.selectOptions(selector, 'AAAAAAAA')
    await userEvent.click(screen.getByRole('button', { name: /보고서\(TXT\) 보기/ }))

    await waitFor(() => expect(getReportText).toHaveBeenCalledWith('AAAAAAAA'))
    expect(screen.getByText('REPORT for AAAAAAAA')).toBeInTheDocument()
  })

  it('defaults to the latest run', async () => {
    const history = [run('BBBBBBBB'), run('AAAAAAAA')]
    getReportText.mockResolvedValue('latest report')
    render(<ReportExportPanel history={history} />)
    await userEvent.click(screen.getByRole('button', { name: /보고서\(TXT\) 보기/ }))
    await waitFor(() => expect(getReportText).toHaveBeenCalledWith('BBBBBBBB'))
  })

  it('shows a placeholder when there are no runs yet', () => {
    render(<ReportExportPanel history={[]} />)
    expect(screen.getByText(/실행 후 보고서/)).toBeInTheDocument()
  })

  it("a late report for A does not appear after the user switched to B (CLOSE-05)", async () => {
    // A's report is deferred; pre-observe its rejection-free resolution to avoid environment noise.
    let resolveA!: (v: string) => void
    const promiseA = new Promise<string>((r) => (resolveA = r))
    getReportText.mockReturnValueOnce(promiseA)
    const history = [run('BBBBBBBB'), run('AAAAAAAA')]
    render(<ReportExportPanel history={history} />)

    // Ask for A's report (stays in flight), then switch the selector to B.
    await userEvent.selectOptions(screen.getByLabelText(/보고서 대상 실행/), 'AAAAAAAA')
    await userEvent.click(screen.getByRole('button', { name: /보고서\(TXT\) 보기/ }))
    await userEvent.selectOptions(screen.getByLabelText(/보고서 대상 실행/), 'BBBBBBBB')

    // A's response arrives late — the sequence guard must discard it (B is selected now).
    await act(async () => {
      resolveA('REPORT for AAAAAAAA')
      await promiseA
    })
    expect(screen.queryByText('REPORT for AAAAAAAA')).not.toBeInTheDocument()
  })
})
