// Local bookmarks to server-saved scenarios.
//
// Only *pointers* (scenario id + name) are kept in localStorage — never the scenario content. The
// authoritative data lives on the server and is fetched on load; this is a bookmark list, not a
// persistence layer masquerading as server storage (FRONTEND_IMPLEMENTATION_SPEC §6, FE-16). Every
// access is guarded so a blocked/empty localStorage degrades to "no saved scenarios".

const KEY = 'passbudget.savedScenarios.v1'

export interface SavedScenarioPointer {
  scenarioId: string
  stableKey: string
  name: string
  savedAt: string
}

export function loadPointers(): SavedScenarioPointer[] {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (p): p is SavedScenarioPointer =>
        typeof p?.scenarioId === 'string' && typeof p?.name === 'string',
    )
  } catch {
    return []
  }
}

export function savePointers(pointers: SavedScenarioPointer[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(pointers))
  } catch {
    // A blocked or full store is non-fatal: the scenario is still saved on the server; only the
    // local bookmark is lost.
  }
}

export function addPointer(pointer: SavedScenarioPointer): SavedScenarioPointer[] {
  const next = [pointer, ...loadPointers().filter((p) => p.scenarioId !== pointer.scenarioId)]
  savePointers(next)
  return next
}

export function removePointer(scenarioId: string): SavedScenarioPointer[] {
  const next = loadPointers().filter((p) => p.scenarioId !== scenarioId)
  savePointers(next)
  return next
}
