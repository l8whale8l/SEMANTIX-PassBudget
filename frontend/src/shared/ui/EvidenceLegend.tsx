// A collapsible key for the per-field evidence dots: what each colour means and how many fields in
// the current panel carry each mark. Collapsed by default. Display only — nothing here affects the
// calculation.

import { evidenceMeta, type EvidenceCounts, type EvidenceMark } from './evidence'

export interface EvidenceLegendProps {
  counts: EvidenceCounts
}

const SHOWN: readonly EvidenceMark[] = ['measured', 'provisional', 'assumption', 'unset']

export function EvidenceLegend({ counts }: EvidenceLegendProps) {
  return (
    <details className="evidence-legend">
      <summary className="evidence-legend__summary">값 근거</summary>
      <ul className="evidence-legend__items">
        {SHOWN.map((mark) => {
          const meta = evidenceMeta(mark)
          return (
            <li key={mark} className="evidence-legend__item" title={meta.label}>
              <span className={`evidence-dot evidence-dot--${meta.tone} evidence-dot--static`} aria-hidden="true" />
              <span className="evidence-legend__label">
                {meta.label} <span className="evidence-legend__count">{counts[mark]}</span>
              </span>
            </li>
          )
        })}
      </ul>
    </details>
  )
}
