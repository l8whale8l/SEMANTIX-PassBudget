import { useEffect, useRef, useState } from 'react'

export interface ScenarioMenuProps {
  name: string
  /** True once the scenario has been saved to the server (enables revision-save wording). */
  saved: boolean
  unsaved: boolean
  onNew: () => void
  onRename: (name: string) => void
  /** Opens the library panel: 'open' shows load/clone lists, 'save' shows the save buttons. */
  onOpenLibrary: (mode: 'open' | 'save') => void
}

/**
 * The scenario “file” menu in the top-left — the tool's file entry point. It gathers the scenario-level
 * operations (new, rename, open/recent, duplicate, save / save as new revision) without merging
 * operations that mean different things: the two save variants and the open/clone flows stay in the
 * library panel, which this menu opens. There is no separate "preset" concept — the two built-in
 * scenarios appear in the same open/save library list. This is screen state; it never touches the hash.
 */
export function ScenarioMenu(props: ScenarioMenuProps) {
  const { name, saved, unsaved, onNew, onRename, onOpenLibrary } = props
  const [open, setOpen] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState(name)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDocDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) close()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    document.addEventListener('mousedown', onDocDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  function close() {
    setOpen(false)
    setRenaming(false)
  }

  const run = (fn: () => void) => () => {
    fn()
    close()
  }

  const startRename = () => {
    setRenameValue(name)
    setRenaming(true)
  }
  const commitRename = () => {
    const next = renameValue.trim()
    if (next) onRename(next)
    close()
  }

  return (
    <div className="scenmenu" ref={rootRef}>
      <button
        type="button"
        className="scenmenu__trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        title="시나리오 메뉴"
      >
        <span className="scenmenu__name">{name || '이름 없는 시나리오'}</span>
        {unsaved ? <span className="scenmenu__dot" title="저장되지 않은 변경" aria-label="저장되지 않은 변경" /> : null}
        <span className="scenmenu__caret" aria-hidden="true">▾</span>
      </button>

      {open ? (
        <div className="scenmenu__pop" role="menu">
          {renaming ? (
            <div className="scenmenu__rename">
              <label htmlFor="scen-rename" className="scenmenu__label">시나리오 이름</label>
              <input
                id="scen-rename"
                className="scenmenu__input"
                value={renameValue}
                autoFocus
                onChange={(e) => setRenameValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitRename()
                  if (e.key === 'Escape') setRenaming(false)
                }}
              />
              <div className="scenmenu__rename-actions">
                <button type="button" className="btn btn--primary" onClick={commitRename}>확인</button>
                <button type="button" className="btn btn--link" onClick={() => setRenaming(false)}>취소</button>
              </div>
            </div>
          ) : (
            <>
              <button type="button" role="menuitem" className="scenmenu__item" onClick={run(onNew)}>
                새 시나리오
              </button>

              <div className="scenmenu__sep" role="separator" />

              <button type="button" role="menuitem" className="scenmenu__item" onClick={startRename}>
                이름 변경…
              </button>

              <div className="scenmenu__sep" role="separator" />

              <button type="button" role="menuitem" className="scenmenu__item" onClick={run(() => onOpenLibrary('open'))}>
                열기 · 최근 시나리오…
              </button>
              <button type="button" role="menuitem" className="scenmenu__item" onClick={run(() => onOpenLibrary('open'))}>
                복제…
              </button>
              <button type="button" role="menuitem" className="scenmenu__item" onClick={run(() => onOpenLibrary('save'))}>
                {saved ? '저장 · 새 리비전으로 저장…' : '저장…'}
              </button>
            </>
          )}
        </div>
      ) : null}
    </div>
  )
}
