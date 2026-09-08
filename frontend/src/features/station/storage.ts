// Local bookmarks to server-saved GROUND_STATION presets (mirrors features/satellite/storage.ts).
//
// Only pointers (profile id + friendly name) live in localStorage — never the station payload. The
// authoritative preset lives on the server (SQLite-persistent) and is fetched on load. Every access
// is guarded so a blocked/empty store degrades to "no saved stations".

const KEY = 'passbudget.savedStations.v1'

export interface SavedStationPointer {
  profileId: string
  stableKey: string
  name: string
  savedAt: string
}

export function loadStationPointers(): SavedStationPointer[] {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (p): p is SavedStationPointer =>
        typeof p?.profileId === 'string' && typeof p?.name === 'string',
    )
  } catch {
    return []
  }
}

function saveStationPointers(pointers: SavedStationPointer[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(pointers))
  } catch {
    // Non-fatal: the preset is still on the server; only the local bookmark is lost.
  }
}

export function addStationPointer(pointer: SavedStationPointer): SavedStationPointer[] {
  const next = [pointer, ...loadStationPointers().filter((p) => p.profileId !== pointer.profileId)]
  saveStationPointers(next)
  return next
}

export function removeStationPointer(profileId: string): SavedStationPointer[] {
  const next = loadStationPointers().filter((p) => p.profileId !== profileId)
  saveStationPointers(next)
  return next
}
