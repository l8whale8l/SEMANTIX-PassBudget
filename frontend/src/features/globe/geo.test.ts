import { describe, expect, it } from 'vitest'
import { ecefToGeodetic, geodeticToEcef, mmToM, udegToDeg, WGS84_A } from './geo'

describe('geo unit conversions', () => {
  it('converts micro-degrees and millimetres to degrees and metres', () => {
    expect(udegToDeg(37_600_000)).toBeCloseTo(37.6, 9)
    expect(udegToDeg(-90_000_000)).toBeCloseTo(-90, 9)
    expect(mmToM(100_000)).toBeCloseTo(100, 9)
  })
})

describe('geodeticToEcef', () => {
  it('places (0,0,0) on the +X axis at the equatorial radius', () => {
    const p = geodeticToEcef({ latitudeDeg: 0, longitudeDeg: 0, heightM: 0 })
    expect(p.x).toBeCloseTo(WGS84_A, 3)
    expect(p.y).toBeCloseTo(0, 3)
    expect(p.z).toBeCloseTo(0, 3)
  })

  it('places (0,90E,0) on the +Y axis', () => {
    const p = geodeticToEcef({ latitudeDeg: 0, longitudeDeg: 90, heightM: 0 })
    expect(p.x).toBeCloseTo(0, 3)
    expect(p.y).toBeCloseTo(WGS84_A, 3)
    expect(p.z).toBeCloseTo(0, 3)
  })

  it('puts the north pole on +Z (polar radius, ~6356.75 km)', () => {
    const p = geodeticToEcef({ latitudeDeg: 90, longitudeDeg: 0, heightM: 0 })
    expect(p.x).toBeCloseTo(0, 3)
    expect(p.y).toBeCloseTo(0, 3)
    expect(p.z).toBeCloseTo(6_356_752.314, 0) // WGS-84 polar semi-minor axis
  })
})

describe('geodetic ↔ ECEF round-trip', () => {
  it('recovers the two preset stations within a millimetre', () => {
    for (const site of [
      { latitudeDeg: 37.6, longitudeDeg: 127, heightM: 100 },
      { latitudeDeg: 0, longitudeDeg: 60, heightM: 0 },
    ]) {
      const back = ecefToGeodetic(geodeticToEcef(site))
      expect(back.latitudeDeg).toBeCloseTo(site.latitudeDeg, 6)
      expect(back.longitudeDeg).toBeCloseTo(site.longitudeDeg, 6)
      expect(back.heightM).toBeCloseTo(site.heightM, 3)
    }
  })
})
