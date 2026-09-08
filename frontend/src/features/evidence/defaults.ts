// Display-only evidence marks for bundled public scenarios. These values never affect calculation.

import type { EvidenceMark } from '../../shared/ui/evidence'

const DEFAULT_EVIDENCE_MARKS: Record<string, Record<string, EvidenceMark>> = {
  'PB-GOLDEN-ORB-01': {
    'orbit:epoch': 'assumption',
    'orbit:semiMajorAxisMm': 'assumption',
    'orbit:eccentricityPpb': 'assumption',
    'orbit:inclinationUdeg': 'assumption',
    'orbit:raanUdeg': 'assumption',
    'orbit:argumentOfPerigeeUdeg': 'assumption',
    'orbit:trueAnomalyUdeg': 'assumption',
    'orbit:muM3PerS2': 'measured',
    'station:SYN-GS-EQUATOR:latitudeUdeg': 'assumption',
    'station:SYN-GS-EQUATOR:longitudeEastUdeg': 'assumption',
    'station:SYN-GS-EQUATOR:ellipsoidalHeightMm': 'assumption',
    'station:SYN-GS-EQUATOR:minimumElevationUdeg': 'assumption',
    'station:SYN-GS-EQUATOR:rate': 'assumption',
    'station:SYN-GS-EQUATOR:efficiency': 'assumption',
    'station:SYN-GS-MIDLAT:latitudeUdeg': 'assumption',
    'station:SYN-GS-MIDLAT:longitudeEastUdeg': 'assumption',
    'station:SYN-GS-MIDLAT:ellipsoidalHeightMm': 'assumption',
    'station:SYN-GS-MIDLAT:minimumElevationUdeg': 'assumption',
    'station:SYN-GS-MIDLAT:rate': 'assumption',
    'station:SYN-GS-MIDLAT:efficiency': 'assumption',
  },
}

/** Default marks for a scenario key (empty when none are defined). */
export function defaultEvidenceMarks(scenarioKey: string): Record<string, EvidenceMark> {
  return DEFAULT_EVIDENCE_MARKS[scenarioKey] ?? {}
}
