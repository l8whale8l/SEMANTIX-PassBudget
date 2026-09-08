import { useState } from 'react'

import { formatBytesAdaptive } from '../../shared/format/units'
import { formatUtcClock } from '../../shared/format/time'
import { deliveryStatusLabel, type DeliveryRow } from './delivery'

export interface DeliveryProgressPanelProps {
  rows: DeliveryRow[]
  /** The globe/timeline's currently selected instant (ISO UTC) — the panel reads this, never a clock. */
  atIso: string
}

/**
 * A small, collapsible panel at the globe's top-left showing each output's planned transfer up to the
 * selected time (spec §8). Shown only in QUEUE_AWARE. Every number is the PLANNED amount at the
 * selected instant from the backend's allocation plan — never a real receipt or ACK. It reads the same
 * run and the same selected time as the globe and timeline; moving the clock back reproduces the same
 * values (the underlying function is deterministic in T).
 */
export function DeliveryProgressPanel({ rows, atIso }: DeliveryProgressPanelProps) {
  const [collapsed, setCollapsed] = useState(false)
  return (
    <section className={collapsed ? 'delivery delivery--collapsed' : 'delivery'} aria-label="출력 전송 진행(계획상)">
      <div className="delivery__bar">
        <button
          type="button"
          className="delivery__toggle"
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((c) => !c)}
        >
          {collapsed ? '▸' : '▾'} 출력 전송 진행 (계획상)
        </button>
        <span className="delivery__time mono" title="선택 시각">{formatUtcClock(atIso)} UTC</span>
      </div>
      {!collapsed ? (
        <div className="delivery__body">
          {rows.length === 0 ? (
            <p className="delivery__empty">표시할 출력물이 없습니다.</p>
          ) : (
            <ul className="delivery__list">
              {rows.map((r) => (
                <li key={r.payloadKey} className="delivery__row">
                  <div className="delivery__rowhead">
                    <span className="delivery__emoji" aria-hidden="true">{r.emoji}</span>
                    <span className="delivery__name" title={r.payloadKey}>{r.name}</span>
                    <span className="delivery__status">{deliveryStatusLabel(r.status)}</span>
                  </div>
                  <div
                    className="delivery__track"
                    role="progressbar"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Math.round(r.fraction * 100)}
                  >
                    <div className="delivery__fill" style={{ width: `${Math.round(r.fraction * 100)}%` }} />
                  </div>
                  <div className="delivery__amount">
                    <span title={`${r.plannedBytes} B`}>{formatBytesAdaptive(r.plannedBytes)}</span>
                    {' / '}
                    <span title={`${r.totalBytes} B`}>{formatBytesAdaptive(r.totalBytes)}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </section>
  )
}
