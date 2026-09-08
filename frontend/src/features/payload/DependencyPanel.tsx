import { useState } from 'react'
import type { DependencyForm, PayloadForm } from '../scenario/draft'

export interface DependencyPanelProps {
  dependencies: DependencyForm[]
  payloads: PayloadForm[]
  onAdd: (predecessorKey: string, successorKey: string) => void
  onRemove: (editId: string) => void
}

/**
 * View, add and remove payload dependencies (predecessor → successor). A payload referenced here
 * cannot be deleted or renamed in the cart until its dependency is removed — the reference is
 * surfaced rather than silently dropped.
 */
export function DependencyPanel({ dependencies, payloads, onAdd, onRemove }: DependencyPanelProps) {
  const [predecessor, setPredecessor] = useState('')
  const [successor, setSuccessor] = useState('')
  const keys = payloads.map((p) => p.stableKey)

  const canAdd =
    predecessor !== '' &&
    successor !== '' &&
    predecessor !== successor &&
    !dependencies.some((d) => d.predecessorKey === predecessor && d.successorKey === successor)

  return (
    <fieldset className="card">
      <legend>출력 의존성 ({dependencies.length})</legend>
      <p className="hint">
        predecessor를 먼저 보낸 뒤 successor를 보냅니다. NETWORK_ONLY 실행에서는 의존성이 제외됩니다.
      </p>

      {dependencies.length > 0 ? (
        <ul className="dependency-list">
          {dependencies.map((d) => (
            <li key={d.editId} className="dependency-item">
              <span className="mono">
                {d.predecessorKey} → {d.successorKey}
              </span>
              <span className="hint"> ({d.kind})</span>
              <button type="button" className="btn btn--link" onClick={() => onRemove(d.editId)}>
                제거
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="hint">의존성이 없습니다.</p>
      )}

      {payloads.length >= 2 ? (
        <div className="dependency-add">
          <div className="row">
            <div className="unit-field">
              <label htmlFor="dep-pred">predecessor (먼저)</label>
              <select id="dep-pred" value={predecessor} onChange={(e) => setPredecessor(e.target.value)}>
                <option value="">선택…</option>
                {keys.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </div>
            <div className="unit-field">
              <label htmlFor="dep-succ">successor (나중)</label>
              <select id="dep-succ" value={successor} onChange={(e) => setSuccessor(e.target.value)}>
                <option value="">선택…</option>
                {keys.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <button
            type="button"
            className="btn btn--secondary"
            disabled={!canAdd}
            onClick={() => {
              onAdd(predecessor, successor)
              setPredecessor('')
              setSuccessor('')
            }}
          >
            의존성 추가
          </button>
        </div>
      ) : (
        <p className="hint">의존성을 추가하려면 출력물이 두 개 이상 필요합니다.</p>
      )}
    </fieldset>
  )
}
