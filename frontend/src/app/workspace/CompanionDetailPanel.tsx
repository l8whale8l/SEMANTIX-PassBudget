import { useEffect, useState, type ReactNode } from 'react'
import type { PanelPosition } from './usePanels'

const DEFAULT_WIDTH = 380
const GAP = 10

export interface CompanionDetailPanelProps {
  title: string
  /** The parent panel's top-left; the companion sticks to the parent's right and follows it. */
  anchorPos: PanelPosition
  anchorWidth: number
  z: number
  asDrawer: boolean
  onClose: () => void
  children: ReactNode
  width?: number
}

/**
 * A detail window attached to the RIGHT of its parent floating panel (spec: the station/output detail
 * opens beside the list, not inline below). Its position is DERIVED from the parent's position, so it
 * moves together when the parent is dragged; the caller only renders it while the parent is open and an
 * item is selected, so closing the parent closes it and selecting another item swaps its content. It is
 * not independently draggable (it belongs to the parent). If there is no room on the right it flips to
 * the left; on small screens it falls back to a bottom drawer.
 */
export function CompanionDetailPanel(props: CompanionDetailPanelProps) {
  const { title, anchorPos, anchorWidth, z, asDrawer, onClose, children } = props
  const width = props.width ?? DEFAULT_WIDTH

  // Reposition on window resize (position is computed from live viewport dimensions).
  const [, forceTick] = useState(0)
  useEffect(() => {
    if (asDrawer) return
    const onResize = () => forceTick((n) => n + 1)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [asDrawer])

  const header = (
    <div className="fpanel__bar fpanel__bar--static">
      <span className="fpanel__title">{title}</span>
      <div className="fpanel__bar-actions">
        <button type="button" className="fpanel__btn" onClick={onClose} title="닫기" aria-label="상세 창 닫기">
          ✕
        </button>
      </div>
    </div>
  )

  if (asDrawer) {
    return (
      <div className="fpanel fpanel--drawer fpanel--companion" role="dialog" aria-label={title} style={{ zIndex: z }}>
        {header}
        <div className="fpanel__body">{children}</div>
      </div>
    )
  }

  const vw = window.innerWidth
  const vh = window.innerHeight
  let left = anchorPos.x + anchorWidth + GAP
  if (left + width > vw) left = anchorPos.x - width - GAP // flip to the left if no room on the right
  left = Math.min(Math.max(left, 0), Math.max(0, vw - width))
  const top = Math.min(Math.max(anchorPos.y, 0), Math.max(0, vh - 44))

  return (
    <div className="fpanel fpanel--companion" role="dialog" aria-label={title} style={{ left, top, zIndex: z, width }}>
      {header}
      <div className="fpanel__body">{children}</div>
    </div>
  )
}
