// Pure geodetic / Earth-fixed geometry for the globe view (F5).
//
// Display-only. These helpers convert the scenario's stored integer micro-units into the floating
// WGS-84 positions Cesium needs, and back. They never feed the engine: the transfer budget and the
// contact windows come from the backend result unchanged; nothing here re-derives a computed value.

/** WGS-84 ellipsoid constants (metres). */
export const WGS84_A = 6_378_137.0
const WGS84_F = 1 / 298.257223563
const WGS84_E2 = WGS84_F * (2 - WGS84_F)

export interface Ecef {
  /** metres, Earth-centred Earth-fixed. */
  x: number
  y: number
  z: number
}

export interface Geodetic {
  /** degrees, north-positive. */
  latitudeDeg: number
  /** degrees, east-positive. */
  longitudeDeg: number
  /** metres above the WGS-84 ellipsoid. */
  heightM: number
}

/** Micro-degrees (stored integer form) → degrees. */
export function udegToDeg(udeg: number): number {
  return udeg / 1_000_000
}

/** Millimetres (stored integer form) → metres. */
export function mmToM(mm: number): number {
  return mm / 1_000
}

const DEG = Math.PI / 180

/** Geodetic (WGS-84) → ECEF metres. Standard closed form. */
export function geodeticToEcef(site: Geodetic): Ecef {
  const lat = site.latitudeDeg * DEG
  const lon = site.longitudeDeg * DEG
  const h = site.heightM
  const sinLat = Math.sin(lat)
  const cosLat = Math.cos(lat)
  const n = WGS84_A / Math.sqrt(1 - WGS84_E2 * sinLat * sinLat)
  return {
    x: (n + h) * cosLat * Math.cos(lon),
    y: (n + h) * cosLat * Math.sin(lon),
    z: (n * (1 - WGS84_E2) + h) * sinLat,
  }
}

/** ECEF metres → geodetic (WGS-84), via Bowring's method (a few iterations, ample for display). */
export function ecefToGeodetic(p: Ecef): Geodetic {
  const lon = Math.atan2(p.y, p.x)
  const r = Math.hypot(p.x, p.y)
  let lat = Math.atan2(p.z, r * (1 - WGS84_E2))
  for (let i = 0; i < 6; i++) {
    const sinLat = Math.sin(lat)
    const n = WGS84_A / Math.sqrt(1 - WGS84_E2 * sinLat * sinLat)
    const h = r / Math.cos(lat) - n
    lat = Math.atan2(p.z, r * (1 - (WGS84_E2 * n) / (n + h)))
  }
  const sinLat = Math.sin(lat)
  const n = WGS84_A / Math.sqrt(1 - WGS84_E2 * sinLat * sinLat)
  const height = r / Math.cos(lat) - n
  return {
    latitudeDeg: lat / DEG,
    longitudeDeg: lon / DEG,
    heightM: height,
  }
}
