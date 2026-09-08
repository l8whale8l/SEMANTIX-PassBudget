import { useRef, useState } from 'react'
import type { SubmittedRun } from '../scenario/useRunScenario'
import { api, ApiError, NetworkError } from '../../shared/api/client'
import { StatusPanel } from '../../shared/ui/StatusPanel'

export interface ReportExportPanelProps {
  /** This session's runs, newest first. The user picks which run (A or B …) to export. */
  history: SubmittedRun[]
}

function download(filename: string, text: string, mime: string) {
  const blob = new Blob([text], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function runLabel(run: SubmittedRun): string {
  return `${run.metadata.run_id.slice(0, 8)}… · ${run.context.analysisMode} · 지상국 ${run.context.activeStationKeys.length}`
}

export function ReportExportPanel({ history }: ReportExportPanelProps) {
  const [selectedId, setSelectedId] = useState<string>('')
  const [report, setReport] = useState<string | null>(null)
  const [reportedId, setReportedId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Guards against an out-of-order report response: only the newest request may write state, so a
  // late report for run A never appears while run B is selected (CLOSE-05).
  const seqRef = useRef(0)

  if (history.length === 0) {
    return (
      <section className="card">
        <h3>보고서·내보내기</h3>
        <p className="hint">실행 후 보고서(TXT)와 결과 JSON을 내보낼 수 있습니다.</p>
      </section>
    )
  }

  // Default to the latest run; the selector lets the user switch to an earlier run (A/B).
  const run = history.find((r) => r.metadata.run_id === selectedId) ?? history[0]
  const runId = run.metadata.run_id

  const loadReport = async () => {
    const seq = ++seqRef.current
    const requestedRunId = runId
    setBusy(true)
    setError(null)
    try {
      const text = await api.getReportText(requestedRunId)
      if (seqRef.current !== seq) return // a newer request superseded this one
      setReport(text)
      setReportedId(requestedRunId)
    } catch (e) {
      if (seqRef.current !== seq) return
      setReport(null)
      setError(
        e instanceof ApiError
          ? `[${e.code}] ${e.message}`
          : e instanceof NetworkError
            ? e.message
            : (e as Error).message,
      )
    } finally {
      if (seqRef.current === seq) setBusy(false)
    }
  }

  return (
    <section className="card" aria-labelledby="report-title">
      <h3 id="report-title">보고서·내보내기</h3>
      <div className="unit-field">
        <label htmlFor="report-run">보고서 대상 실행</label>
        <select
          id="report-run"
          value={runId}
          onChange={(e) => {
            // Abandon any in-flight report for the previously selected run: bump the sequence so a
            // late response is discarded, and clear the busy/preview state for the new selection.
            seqRef.current++
            setSelectedId(e.target.value)
            setReport(null)
            setError(null)
            setBusy(false)
          }}
        >
          {history.map((r) => (
            <option key={r.metadata.run_id} value={r.metadata.run_id}>
              {runLabel(r)}
            </option>
          ))}
        </select>
      </div>
      <p className="hint">
        run {runId.slice(0, 8)}… · input_snapshot_hash {run.envelope.input_snapshot_hash.slice(0, 12)}… ·
        result_content_hash {run.envelope.result_content_hash.slice(0, 12)}…
      </p>
      <div className="library-actions">
        <button type="button" className="btn btn--secondary" onClick={loadReport} disabled={busy}>
          보고서(TXT) 보기
        </button>
        <button
          type="button"
          className="btn btn--secondary"
          onClick={() =>
            download(
              `passbudget-result-${runId.slice(0, 8)}.json`,
              JSON.stringify(run.envelope, null, 2),
              'application/json',
            )
          }
        >
          결과 JSON 다운로드
        </button>
        {report != null && reportedId === runId ? (
          <button
            type="button"
            className="btn btn--secondary"
            onClick={() => download(`passbudget-report-${runId.slice(0, 8)}.txt`, report, 'text/plain')}
          >
            보고서 TXT 다운로드
          </button>
        ) : null}
      </div>

      {error ? (
        <StatusPanel kind="error" title="보고서 로드 실패">
          {error}
        </StatusPanel>
      ) : null}
      {report != null && reportedId === runId ? (
        <pre className="report-text" aria-label="보고서 미리보기">
          {report}
        </pre>
      ) : null}
    </section>
  )
}
