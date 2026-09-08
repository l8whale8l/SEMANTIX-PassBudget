import { useCallback, useEffect, useRef, type ReactNode } from 'react'
import type { PanelPosition } from './usePanels'

export interface FloatingPanelProps {
  title: string
  open: boolean
  pos: PanelPosition
  z: number
  /** Render as a bottom sheet/drawer instead of a movable window (small screens). */
  asDrawer: boolean
  onClose: () => void
  onFocus: () => void
  onMove: (pos: PanelPosition) => void
  onResetPosition: () => void
  children: ReactNode
  /** Panel width in px (default 380). Wider panels (e.g. the result tables) pass their own. */
  width?: number
  /** Extra title-bar action buttons, rendered before the reset/close buttons. */
  extraActions?: ReactNode
  /** Extra class on the panel root (e.g. to widen the drawer body). */
  className?: string
}

const DEFAULT_PANEL_W = 380

/** Keep the whole title bar — including the reset and close buttons on its right — on screen after a
 *  move or a window resize. The panel stays fully within the viewport horizontally, and its title bar
 *  never drops below the bottom edge. */
function clampToViewport(pos: PanelPosition, width: number): PanelPosition {
  const maxX = Math.max(0, window.innerWidth - width)
  const maxY = Math.max(0, window.innerHeight - 44) // title bar stays reachable
  return {
    x: Math.min(Math.max(pos.x, 0), maxX),
    y: Math.min(Math.max(pos.y, 0), maxY),
  }
}

/**
 * A floating, draggable settings/tool window over the globe. Dragging starts only from the title bar
 * (never from inputs/buttons), the panel comes to front on any interaction, the title bar and close
 * button are always reachable (clamped on move and on window resize), and it collapses to a bottom
 * drawer on small screens. Open/close and reset-position are ordinary focusable buttons, so the panel
 * is fully operable without a mouse. This is screen state; it never touches the run or its hash.
 */
export function FloatingPanel(props: FloatingPanelProps) {
  const { title, open, pos, z, asDrawer, onClose, onFocus, onMove, onResetPosition, children } = props
  const width = props.width ?? DEFAULT_PANEL_W
  const drag = useRef<{ dx: number; dy: number } | null>(null)
  const onMoveRef = useRef(onMove)
  useEffect(() => {
    onMoveRef.current = onMove
  }, [onMove])

  // Re-clamp on window resize so the controls never end up off-screen.
  useEffect(() => {
    if (!open || asDrawer) return
    const onResize = () => onMoveRef.current(clampToViewport(pos, width))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [open, asDrawer, pos, width])

  const onTitlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      // Only the bar itself starts a drag — never a button inside it.
      if ((e.target as HTMLElement).closest('button')) return
      onFocus()
      drag.current = { dx: e.clientX - pos.x, dy: e.clientY - pos.y }
      ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    },
    [onFocus, pos],
  )
  const onTitlePointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!drag.current) return
      onMoveRef.current(
        clampToViewport({ x: e.clientX - drag.current.dx, y: e.clientY - drag.current.dy }, width),
      )
    },
    [width],
  )
  const endDrag = useCallback((e: React.PointerEvent) => {
    drag.current = null
    if ((e.currentTarget as HTMLElement).hasPointerCapture?.(e.pointerId)) {
      ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
    }
  }, [])

  if (!open) return null

  const header = (
    <div
      className="fpanel__bar"
      onPointerDown={asDrawer ? undefined : onTitlePointerDown}
      onPointerMove={asDrawer ? undefined : onTitlePointerMove}
      onPointerUp={asDrawer ? undefined : endDrag}
      onPointerCancel={asDrawer ? undefined : endDrag}
    >
      <span className="fpanel__title">{title}</span>
      <div className="fpanel__bar-actions">
        {props.extraActions}
        {!asDrawer ? (
          <button type="button" className="fpanel__btn" onClick={onResetPosition} title="기본 위치로">
            ⤢
            <span className="sr-only">기본 위치로</span>
          </button>
        ) : null}
        <button type="button" className="fpanel__btn" onClick={onClose} title="닫기" aria-label="닫기">
          ✕
        </button>
      </div>
    </div>
  )

  const rootClass = props.className ? `fpanel ${props.className}` : 'fpanel'

  if (asDrawer) {
    return (
      <div className={`${rootClass} fpanel--drawer`} role="dialog" aria-label={title}>
        {header}
        <div className="fpanel__body">{children}</div>
      </div>
    )
  }

  return (
    <div
      className={rootClass}
      role="dialog"
      aria-label={title}
      style={{ left: pos.x, top: pos.y, zIndex: z, width }}
      onPointerDownCapture={onFocus}
    >
      {header}
      <div className="fpanel__body">{children}</div>
    </div>
  )
}
