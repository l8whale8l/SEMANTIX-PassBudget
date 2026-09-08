// Public browser presets must contain only synthetic data or clearly public provenance.
// Mission-specific working scenarios belong outside this repository and can be entered at runtime.

import orbRaw from './PB-GOLDEN-ORB-01.json'
import type { FixtureContent } from '../../../shared/api/types'

export interface PresetDescriptor {
  /** Stable UI id. Public fixtures can be submitted directly with {"fixture": id}. */
  readonly fixtureId: string
  readonly title: string
  readonly provenance: string
  readonly content: FixtureContent
  readonly isPublicFixture?: boolean
  /** UI-only satellite name; it is not part of the executable snapshot or canonical hash. */
  readonly satelliteName?: string
}

export const ORB_PRESET: PresetDescriptor = {
  fixtureId: 'PB-GOLDEN-ORB-01',
  title: '합성 저궤도 관측 임무',
  provenance: '합성 기준 궤도 / 합성 지상국 2곳 / 가정 기반 전송 조건',
  content: orbRaw as FixtureContent,
  isPublicFixture: true,
  satelliteName: 'SYN-LEO-700',
}

/** Only public, redistributable presets are bundled with the open-source application. */
export const PRESETS: readonly PresetDescriptor[] = [ORB_PRESET]

/** A fresh workspace always opens on the public synthetic reference scenario. */
export const DEFAULT_PRESET: PresetDescriptor = ORB_PRESET
