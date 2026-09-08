import { useState } from 'react'
import { ASSUMED_UNIT_FACTORS, computeAssumedBytes, measureFile, utf8ByteSize } from './measure'
import { formatBytesAdaptive } from '../../shared/format/units'

export interface PayloadDraftInput {
  displayName: string
  logicalSizeBytes: number
  sizeSource: string
}

export interface PayloadImportPanelProps {
  onAdd: (input: PayloadDraftInput) => void
}

type AddMode = 'paste' | 'file' | 'assumed'

/**
 * Adds a model output to the cart via one of three explicit modes (spec §6): paste text (measured as
 * UTF-8 bytes), pick a file (measured by File.size), or enter an assumed size directly in B/KB/MB/GB.
 * Only one mode's controls are shown at a time. Neither pasted text nor file bytes are ever read into a
 * request — only the byte count and a name (FE-12/FE-13). The size source is recorded so the cart can
 * show where a size came from (측정 vs 가정값).
 */
export function PayloadImportPanel({ onAdd }: PayloadImportPanelProps) {
  const [mode, setMode] = useState<AddMode>('paste')
  const [paste, setPaste] = useState('')
  const [pasteName, setPasteName] = useState('')
  const [file, setFile] = useState<{ name: string; sizeBytes: number } | null>(null)
  const [assumedName, setAssumedName] = useState('')
  const [assumedValue, setAssumedValue] = useState('')
  const [assumedUnit, setAssumedUnit] = useState('MB')
  const [message, setMessage] = useState<string | null>(null)

  const pasteBytes = utf8ByteSize(paste)

  const addPaste = () => {
    if (pasteBytes === 0) {
      setMessage('빈 텍스트는 추가할 수 없습니다 (0바이트는 현재 DTO가 허용하지 않습니다).')
      return
    }
    onAdd({
      displayName: pasteName.trim() || 'pasted-output',
      logicalSizeBytes: pasteBytes,
      sizeSource: `붙여넣기 측정 (${pasteBytes.toLocaleString()} B)`,
    })
    setPaste('')
    setPasteName('')
    setMessage(null)
  }

  const addFile = () => {
    if (!file) return
    if (file.sizeBytes === 0) {
      setMessage('0바이트 파일은 추가할 수 없습니다 (현재 DTO는 양의 크기만 허용).')
      return
    }
    onAdd({
      displayName: file.name,
      logicalSizeBytes: file.sizeBytes,
      sizeSource: `파일 측정: ${file.name}`,
    })
    setFile(null)
    setMessage(null)
  }

  const assumedBytes = computeAssumedBytes(assumedValue, assumedUnit)
  const addAssumed = () => {
    if (assumedBytes == null || assumedBytes <= 0) {
      setMessage('가정 크기는 양의 정수 바이트로 변환되어야 합니다 (예: 40983 B, 2.5 MB).')
      return
    }
    onAdd({
      displayName: assumedName.trim() || 'assumed-output',
      logicalSizeBytes: assumedBytes,
      sizeSource: `가정값 (${assumedValue} ${assumedUnit})`,
    })
    setAssumedName('')
    setAssumedValue('')
    setMessage(null)
  }

  return (
    <fieldset className="card">
      <legend>＋ 출력 추가</legend>
      <div className="addmode__tabs" role="tablist">
        <ModeTab id="paste" mode={mode} setMode={setMode} label="텍스트 붙여넣기" />
        <ModeTab id="file" mode={mode} setMode={setMode} label="파일 선택" />
        <ModeTab id="assumed" mode={mode} setMode={setMode} label="가정 크기 입력" />
      </div>

      {mode === 'paste' ? (
        <div className="import-block">
          <p className="hint">원문은 서버로 전송되지 않습니다. 브라우저에서 UTF-8 크기(byte)만 측정합니다.</p>
          <label htmlFor="paste-name">이름 (선택)</label>
          <input id="paste-name" value={pasteName} onChange={(e) => setPasteName(e.target.value)} placeholder="예: wildfire_detection.geojson" />
          <label htmlFor="paste-body">붙여넣기 (UTF-8 원문)</label>
          <textarea id="paste-body" value={paste} onChange={(e) => setPaste(e.target.value)} rows={4} spellCheck={false} placeholder="모델 출력 텍스트를 붙여넣으세요" />
          <div className="import-actions">
            <span className="hint">측정 크기: {formatBytesAdaptive(pasteBytes)} ({pasteBytes.toLocaleString()} B)</span>
            <button type="button" className="btn btn--secondary" onClick={addPaste} disabled={pasteBytes === 0}>붙여넣기 추가</button>
          </div>
        </div>
      ) : mode === 'file' ? (
        <div className="import-block">
          <p className="hint">파일 내용은 읽지 않고 크기(byte)만 사용합니다.</p>
          <label htmlFor="file-pick">파일 선택 (크기만 읽음)</label>
          <input id="file-pick" type="file" onChange={(e) => { const f = e.target.files?.[0]; setFile(f ? measureFile(f) : null); setMessage(null) }} />
          {file ? (
            <div className="import-actions">
              <span className="hint">{file.name} — {formatBytesAdaptive(file.sizeBytes)} ({file.sizeBytes.toLocaleString()} B)</span>
              <button type="button" className="btn btn--secondary" onClick={addFile}>파일 추가</button>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="import-block">
          <p className="hint">실제 파일이 없을 때 가정 크기를 직접 입력합니다. 정확한 정수 바이트로 변환됩니다.</p>
          <label htmlFor="assumed-name">이름 (선택)</label>
          <input id="assumed-name" value={assumedName} onChange={(e) => setAssumedName(e.target.value)} placeholder="예: assumed_scene" />
          <div className="row">
            <div className="unit-field">
              <label htmlFor="assumed-value">가정 크기</label>
              <input id="assumed-value" inputMode="decimal" value={assumedValue} onChange={(e) => setAssumedValue(e.target.value)} placeholder="예: 40983 또는 2.5" />
            </div>
            <div className="unit-field">
              <label htmlFor="assumed-unit">단위</label>
              <select id="assumed-unit" value={assumedUnit} onChange={(e) => setAssumedUnit(e.target.value)}>
                {Object.keys(ASSUMED_UNIT_FACTORS).map((u) => <option key={u} value={u}>{u}</option>)}
              </select>
            </div>
          </div>
          <div className="import-actions">
            <span className="hint">
              {assumedBytes != null ? `= ${assumedBytes.toLocaleString()} B (${formatBytesAdaptive(assumedBytes)})` : '정수 바이트로 변환 가능한 값이어야 합니다'}
            </span>
            <button type="button" className="btn btn--secondary" onClick={addAssumed} disabled={assumedBytes == null || assumedBytes <= 0}>가정값 추가</button>
          </div>
        </div>
      )}

      {message ? <p className="unit-field__error" role="alert">{message}</p> : null}
    </fieldset>
  )
}

function ModeTab({ id, mode, setMode, label }: { id: AddMode; mode: AddMode; setMode: (m: AddMode) => void; label: string }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={mode === id}
      className={mode === id ? 'addmode__tab addmode__tab--active' : 'addmode__tab'}
      onClick={() => setMode(id)}
    >
      {label}
    </button>
  )
}
