// Local bookmarks to server-saved SATELLITE presets (SPACECRAFT profiles).
//
// Mirrors the scenario library: only *pointers* (profile id + name) live in localStorage — never the
// orbit payload. The authoritative preset lives on the server (SQLite-persistent) and is fetched on
// load. Every access is guarded so a blocked/empty store degrades to "no saved satellites".

const KEY = 'passbudget.savedSatellites.v1'

export interface SavedSatellitePointer {
  profileId: string
  stableKey: string
  name: string
  savedAt: string
}

export function loadSatellitePointers(): SavedSatellitePointer[] {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (p): p is SavedSatellitePointer =>
        typeof p?.profileId === 'string' && typeof p?.name === 'string',
    )
  } catch {
    return []
  }
}

function saveSatellitePointers(pointers: SavedSatellitePointer[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(pointers))
  } catch {
    // Non-fatal: the preset is still on the server; only the local bookmark is lost.
  }
}

export function addSatellitePointer(pointer: SavedSatellitePointer): SavedSatellitePointer[] {
  const next = [pointer, ...loadSatellitePointers().filter((p) => p.profileId !== pointer.profileId)]
  saveSatellitePointers(next)
  return next
}

export function removeSatellitePointer(profileId: string): SavedSatellitePointer[] {
  const next = loadSatellitePointers().filter((p) => p.profileId !== profileId)
  saveSatellitePointers(next)
  return next
}
