// Evidence / decision-grade badge.
//
// Estimates must never read as measured facts (ADR-0005 §5). This badge renders an evidence or
// decision grade as text (not colour alone, §8), so a proxy-derived result is always marked.

export type BadgeTone = 'assumption' | 'concept' | 'info' | 'warn'

export interface AssumptionBadgeProps {
  tone: BadgeTone
  label: string
  title?: string
}

export function AssumptionBadge({ tone, label, title }: AssumptionBadgeProps) {
  return (
    <span className={`badge badge--${tone}`} title={title}>
      {label}
    </span>
  )
}
