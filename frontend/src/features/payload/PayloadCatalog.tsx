import type { PayloadDTO } from '../../shared/api/types'
import { formatBytesAdaptive } from '../../shared/format/units'
import { segmentationLabel, serviceClassLabel } from '../../shared/format/labels'

export interface PayloadCatalogProps {
  /** Preset outputs available to re-add this session (not a persisted catalog — that is the library). */
  templates: PayloadDTO[]
  /** Stable keys currently in the cart, to hide already-added templates. */
  currentKeys: Set<string>
  onAdd: (template: PayloadDTO) => void
}

/**
 * “템플릿 불러오기” — a this-session template list to re-add a preset output that was removed from the
 * cart (spec §6). It is a collapsed entry point, not a permanently expanded list, and is clearly a
 * this-session draft catalog, not a persisted library (that is the scenario library).
 */
export function PayloadCatalog({ templates, currentKeys, onAdd }: PayloadCatalogProps) {
  const available = templates.filter((t) => !currentKeys.has(t.stable_key))
  if (available.length === 0) return null
  return (
    <details className="card cart-collapsible">
      <summary>템플릿 불러오기 ({available.length})</summary>
      <p className="hint">이번 세션 초안 템플릿입니다. 영속 저장·복원은 시나리오 저장/불러오기에서 제공됩니다.</p>
      <ul className="catalog-list">
        {available.map((t) => (
          <li key={t.stable_key} className="catalog-item">
            <span className="mono">{t.display_name ?? t.stable_key}</span>
            <span className="hint">
              {formatBytesAdaptive(t.logical_size_bytes)} · {serviceClassLabel(t.service_class)} ·{' '}
              {segmentationLabel(t.segmentation)}
            </span>
            <button type="button" className="btn btn--secondary" onClick={() => onAdd(t)}>
              추가
            </button>
          </li>
        ))}
      </ul>
    </details>
  )
}
