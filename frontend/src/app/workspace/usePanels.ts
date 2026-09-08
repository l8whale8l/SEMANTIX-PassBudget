import { useCallback, useState } from 'react'

// Floating-panel window state for the globe workspace. This is *screen* state only: it never enters
// the scenario input or the run hash, and moving/opening a panel never triggers a recompute.

export type PanelId = 'settings' | 'cart' | 'library' | 'compare' | 'report' | 'help'

export const PANEL_IDS: PanelId[] = ['settings', 'cart', 'library', 'compare', 'report', 'help']

export interface PanelPosition {
  x: number
  y: number
}

interface PanelState {
  open: boolean
  pos: PanelPosition
  z: number
}

/** Default top-left for each panel, staggered so opening several does not stack them exactly. */
const DEFAULT_POS: Record<PanelId, PanelPosition> = {
  settings: { x: 96, y: 88 },
  cart: { x: 150, y: 128 },
  library: { x: 204, y: 168 },
  compare: { x: 258, y: 208 },
  report: { x: 312, y: 248 },
  help: { x: 132, y: 108 },
}

function initialState(): Record<PanelId, PanelState> {
  const base = {} as Record<PanelId, PanelState>
  for (const id of PANEL_IDS) base[id] = { open: false, pos: { ...DEFAULT_POS[id] }, z: 1 }
  return base
}

export interface PanelsApi {
  panels: Record<PanelId, PanelState>
  isOpen: (id: PanelId) => boolean
  toggle: (id: PanelId) => void
  open: (id: PanelId) => void
  close: (id: PanelId) => void
  focus: (id: PanelId) => void
  move: (id: PanelId, pos: PanelPosition) => void
  resetPosition: (id: PanelId) => void
  resetAll: () => void
}

export function usePanels(): PanelsApi {
  const [panels, setPanels] = useState<Record<PanelId, PanelState>>(initialState)
  const [topZ, setTopZ] = useState(1)

  const bringToFront = useCallback(
    (id: PanelId) =>
      setPanels((prev) => {
        setTopZ((z) => z + 1)
        return { ...prev, [id]: { ...prev[id], z: topZ + 1 } }
      }),
    [topZ],
  )

  const open = useCallback(
    (id: PanelId) => {
      setTopZ((z) => z + 1)
      setPanels((prev) => ({ ...prev, [id]: { ...prev[id], open: true, z: topZ + 1 } }))
    },
    [topZ],
  )
  const close = useCallback(
    (id: PanelId) => setPanels((prev) => ({ ...prev, [id]: { ...prev[id], open: false } })),
    [],
  )
  const toggle = useCallback(
    (id: PanelId) => {
      setPanels((prev) => {
        const next = !prev[id].open
        if (next) setTopZ((z) => z + 1)
        return { ...prev, [id]: { ...prev[id], open: next, z: next ? topZ + 1 : prev[id].z } }
      })
    },
    [topZ],
  )
  const move = useCallback(
    (id: PanelId, pos: PanelPosition) =>
      setPanels((prev) => ({ ...prev, [id]: { ...prev[id], pos } })),
    [],
  )
  const resetPosition = useCallback(
    (id: PanelId) =>
      setPanels((prev) => ({ ...prev, [id]: { ...prev[id], pos: { ...DEFAULT_POS[id] } } })),
    [],
  )
  const resetAll = useCallback(() => {
    setPanels(initialState())
    setTopZ(1)
  }, [])
  const isOpen = useCallback((id: PanelId) => panels[id].open, [panels])
  const focus = bringToFront

  return { panels, isOpen, toggle, open, close, focus, move, resetPosition, resetAll }
}
