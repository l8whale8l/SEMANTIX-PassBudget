import { useCallback, useRef } from 'react'

import type { SubmittedRun } from '../../features/scenario/useRunScenario'
import { ResultTables, type DockTab } from './ResultTables'
import type { PanelPosition } from './usePanels'

export interface BottomDockProps {
  /** 'closed' shows only a compact entry chip; 'docked' shows the table panel above the timeline. */
  mode: 'closed' | 'docked'
  lastRun: SubmittedRun | null
  selectedPassKey: string | null
  onSelectPass: (key: string | null) => void
  tab: DockTab
  onTabChange: (tab: DockTab) => void
  onOpen: () => void
  onClose: () => void
  /** Detach into a floating window at the given viewport point (from dragging the title bar). */
  onFloat: (pos: PanelPosition) => void
}

const DRAG_THRESHOLD = 6

/**
 * The result dock, docked above the globe's time controls. It has three screen states owned by the
 * shell — this component renders the in-stage two: a small "결과 표" chip when closed, and a docked
 * panel when open. The panel never covers the Cesium timeline/playback (it stops short of the bottom),
 * and dragging its title bar detaches it into a floating window (spec §3-1). Closing leaves only the
 * chip, not a full-width bar. This is screen state; it never touches the run or its hash.
 */
export function BottomDock(props: BottomDockProps) {
  const { mode, lastRun, selectedPassKey, onSelectPass, tab, onTabChange, onOpen, onClose, onFloat } = props
  const dragStart = useRef<{ x: number; y: number; offX: number } | null>(null)
  const floated = useRef(false)

  const onBarPointerDown = useCallback((e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest('button')) return // tabs/buttons don't start a drag
    const bar = e.currentTarget as HTMLElement
    dragStart.current = { x: e.clientX, y: e.clientY, offX: e.clientX - bar.getBoundingClientRect().left }
    floated.current = false
    bar.setPointerCapture(e.pointerId)
  }, [])

  const onBarPointerMove = useCallback(
    (e: React.PointerEvent) => {
      const start = dragStart.current
      if (!start || floated.current) return
      const moved = Math.abs(e.clientX - start.x) + Math.abs(e.clientY - start.y)
      if (moved < DRAG_THRESHOLD) return
      // Detach: place the floating panel so the cursor keeps roughly the same grab point on its bar.
      floated.current = true
      onFloat({ x: e.clientX - start.offX, y: e.clientY - 14 })
    },
    [onFloat],
  )

  const endBarDrag = useCallback((e: React.PointerEvent) => {
    dragStart.current = null
    const bar = e.currentTarget as HTMLElement
    if (bar.hasPointerCapture?.(e.pointerId)) bar.releasePointerCapture(e.pointerId)
  }, [])

  if (mode === 'closed') {
    return (
      <button type="button" className="dock-chip" onClick={onOpen} aria-expanded={false}>
        ▲ 결과 표
      </button>
    )
  }

  return (
    <section className="dock" aria-label="결과 도크">
      <div
        className="dock__bar"
        onPointerDown={onBarPointerDown}
        onPointerMove={onBarPointerMove}
        onPointerUp={endBarDrag}
        onPointerCancel={endBarDrag}
        title="제목 표시줄을 드래그하면 떠 있는 창으로 분리됩니다"
      >
        <span className="dock__grip" aria-hidden="true">⋮⋮</span>
        <span className="dock__heading">결과 표</span>
        <div className="dock__spacer" />
        <button type="button" className="dock__act" onClick={() => onFloat({ x: 24, y: 96 })} title="떠 있는 창으로 분리">
          ⤢ 띄우기
        </button>
        <button type="button" className="dock__act" onClick={onClose} aria-expanded title="닫기 (작은 진입점만 남김)">
          ▼ 닫기
        </button>
      </div>
      <div className="dock__body">
        <ResultTables
          lastRun={lastRun}
          selectedPassKey={selectedPassKey}
          onSelectPass={onSelectPass}
          tab={tab}
          onTabChange={onTabChange}
        />
      </div>
    </section>
  )
}
