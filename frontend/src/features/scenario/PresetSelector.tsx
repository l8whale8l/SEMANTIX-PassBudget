import { PRESETS, type PresetDescriptor } from './presets'
import { AssumptionBadge } from '../../shared/ui/AssumptionBadge'

export interface PresetSelectorProps {
  activeFixtureId: string
  onLoadPreset: (preset: PresetDescriptor) => void
}

export function PresetSelector({ activeFixtureId, onLoadPreset }: PresetSelectorProps) {
  return (
    <div className="preset-selector">
      <label htmlFor="preset-select">프리셋</label>
      <select
        id="preset-select"
        value={activeFixtureId}
        onChange={(e) => {
          const preset = PRESETS.find((p) => p.fixtureId === e.target.value)
          if (preset) onLoadPreset(preset)
        }}
      >
        {PRESETS.map((p) => (
          <option key={p.fixtureId} value={p.fixtureId}>
            {p.title}
          </option>
        ))}
      </select>
      <AssumptionBadge
        tone="assumption"
        label={PRESETS.find((p) => p.fixtureId === activeFixtureId)?.provenance ?? '가정 기반 추정'}
        title="이 값은 실측 비행 성능이 아니라 합성·가정 입력입니다."
      />
    </div>
  )
}
