// Loading / empty / error surface, rendered as text with an ARIA live region so screen readers
// announce state changes (FRONTEND_IMPLEMENTATION_SPEC §8).

import type { ReactNode } from 'react'

export interface StatusPanelProps {
  kind: 'loading' | 'empty' | 'error' | 'info'
  title: string
  children?: ReactNode
}

export function StatusPanel({ kind, title, children }: StatusPanelProps) {
  return (
    <div
      className={`status-panel status-panel--${kind}`}
      role={kind === 'error' ? 'alert' : 'status'}
      aria-live={kind === 'error' ? 'assertive' : 'polite'}
    >
      <strong>{title}</strong>
      {children ? <div className="status-panel__body">{children}</div> : null}
    </div>
  )
}
