import type { PanelId } from './usePanels'

export interface WorkspaceToolbarProps {
  isOpen: (id: PanelId) => boolean
  onToggle: (id: PanelId) => void
  onResetView: () => void
  /** Chase-camera lock (behind/above the satellite, facing it). */
  chaseCam: boolean
  onToggleChase: () => void
}

const TOOLS: { id: PanelId; icon: string; label: string; disabled?: boolean }[] = [
  { id: 'settings', icon: '⚙', label: '설정' },
  { id: 'cart', icon: '🛰', label: '모델 출력 장바구니' },
  { id: 'library', icon: '💾', label: '시나리오 저장/불러오기' },
  { id: 'compare', icon: '⇄', label: '실행 비교 (개발 중)', disabled: true },
  { id: 'report', icon: '📄', label: '보고서 (개발 중)', disabled: true },
  { id: 'help', icon: '❓', label: '도움말' },
]

/** Vertical icon rail (top-right). Each button opens/closes a floating tool panel over the globe; the
 *  last resets the view and panel layout. Buttons are ordinary focusable controls, so every panel is
 *  reachable without a mouse. */
export function WorkspaceToolbar({
  isOpen,
  onToggle,
  onResetView,
  chaseCam,
  onToggleChase,
}: WorkspaceToolbarProps) {
  return (
    <nav className="toolbar" aria-label="작업 도구">
      {TOOLS.map((t) => (
        <button
          key={t.id}
          type="button"
          className={
            (isOpen(t.id) && !t.disabled ? 'toolbar__btn toolbar__btn--active' : 'toolbar__btn') +
            (t.disabled ? ' toolbar__btn--disabled' : '')
          }
          aria-pressed={t.disabled ? undefined : isOpen(t.id)}
          disabled={t.disabled}
          title={t.label}
          onClick={() => onToggle(t.id)}
        >
          <span aria-hidden="true">{t.icon}</span>
          <span className="sr-only">{t.label}</span>
        </button>
      ))}
      <button
        type="button"
        className={chaseCam ? 'toolbar__btn toolbar__btn--active' : 'toolbar__btn'}
        aria-pressed={chaseCam}
        title="위성 추적 시점 (위성 뒤·위에서 위성을 바라보며 따라감)"
        onClick={onToggleChase}
      >
        <span aria-hidden="true">🎥</span>
        <span className="sr-only">위성 추적 시점</span>
      </button>
      <button
        type="button"
        className="toolbar__btn toolbar__btn--reset"
        title="보기/배치 초기화"
        onClick={onResetView}
      >
        <span aria-hidden="true">⟲</span>
        <span className="sr-only">보기/배치 초기화</span>
      </button>
    </nav>
  )
}
