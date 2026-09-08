import { useState } from 'react'
import {
  buildFixtureContent,
  draftFromContent,
  draftFromPreset,
  rebaseSavedDraft,
  saveScopeWarnings,
  type ScenarioDraft,
} from '../scenario/draft'
import { PRESETS, type PresetDescriptor } from '../scenario/presets'
import { api, ApiError, NetworkError } from '../../shared/api/client'
import { addPointer, loadPointers, removePointer, type SavedScenarioPointer } from './storage'
import { StatusPanel } from '../../shared/ui/StatusPanel'

export interface ScenarioLibraryProps {
  draft: ScenarioDraft
  /** True when the current draft has unsaved edits, so loading another scenario confirms first. */
  unsaved: boolean
  /** `switch: true` marks a real scenario change so the shell clears the previous run. */
  onLoadDraft: (draft: ScenarioDraft, opts?: { switch?: boolean }) => void
  /** 'open' hides the save buttons (opened via 열기·최근/복제); 'save' shows them (opened via 저장). */
  mode: 'open' | 'save'
}

function genStableKey(): string {
  const ts = new Date().toISOString().replace(/[^0-9]/g, '').slice(0, 14)
  const rand = Math.random().toString(36).slice(2, 8)
  return `SC-${ts}-${rand}`
}

export function ScenarioLibrary({ draft, unsaved, onLoadDraft, mode }: ScenarioLibraryProps) {
  const [pointers, setPointers] = useState<SavedScenarioPointer[]>(() => loadPointers())
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const describe = (e: unknown): string => {
    if (e instanceof ApiError) {
      // A 404 here means the saved scenario is no longer on the server — most often because the
      // backend catalog is in-memory and the process was restarted. Say so, and point to removal.
      if (e.status === 404) {
        return `${e.message} 서버에 이 시나리오가 없습니다(백엔드가 재시작되었을 수 있습니다). 아래 “제거”로 정리하세요.`
      }
      return `[${e.code}] ${e.message}`
    }
    if (e instanceof NetworkError) return e.message
    return (e as Error).message
  }

  const forgetPointer = (scenarioId: string) => {
    setPointers(removePointer(scenarioId))
    setStatus('로컬 목록에서 제거했습니다 (서버 데이터는 변경하지 않았습니다).')
  }

  // Save the current draft as a brand-new server scenario (create -> publish -> snapshot). Network
  // failures are surfaced, never silently retried (a retried create would duplicate the scenario).
  const saveNew = async () => {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      const content = buildFixtureContent(draft)
      const stableKey = genStableKey()
      const name = draft.scenarioName.trim() || 'scenario'
      const scenario = await api.createScenario({ stable_key: stableKey, name, content })
      const revisionId = scenario.revisions[0].revision_id
      await api.publishScenarioRevision(revisionId)
      await api.createSnapshot(revisionId) // validates the saved input is executable
      setPointers(
        addPointer({ scenarioId: scenario.scenario_id, stableKey, name, savedAt: new Date().toISOString() }),
      )
      // Rebase onto the saved content but KEEP the editing state (inactive stations, cart) — CLOSE-03.
      onLoadDraft(rebaseSavedDraft(draft, content, { scenarioId: scenario.scenario_id, name }))
      setStatus(`저장됨: ${name} (scenario ${scenario.scenario_id.slice(0, 8)}…)`)
    } catch (e) {
      setError(describe(e))
    } finally {
      setBusy(false)
    }
  }

  // Save edits to an already-saved scenario as a NEW published revision (the previous published
  // revision stays immutable on the server).
  const saveRevision = async () => {
    if (!draft.savedScenarioId) return
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      const content = buildFixtureContent(draft)
      const scenarioId = draft.savedScenarioId
      const revision = await api.createScenarioRevision(scenarioId, { content })
      await api.publishScenarioRevision(revision.revision_id)
      await api.createSnapshot(revision.revision_id)
      onLoadDraft(rebaseSavedDraft(draft, content, { scenarioId, name: draft.scenarioName }))
      setStatus(`새 리비전 저장됨 (rev ${revision.revision_no})`)
    } catch (e) {
      setError(describe(e))
    } finally {
      setBusy(false)
    }
  }

  const load = async (pointer: SavedScenarioPointer) => {
    if (
      unsaved &&
      !window.confirm('저장되지 않은 변경이 있습니다. 다른 시나리오를 불러오면 현재 편집 내용이 사라질 수 있습니다. 계속할까요?')
    ) {
      return
    }
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      const scenario = await api.getScenario(pointer.scenarioId)
      // Prefer the published current revision; fall back to the newest revision so a freshly cloned
      // scenario — which the server returns as a DRAFT with no current_revision_id (CLOSE-04) — can
      // still be loaded, edited and run. `/content` reads a DRAFT or a PUBLISHED revision alike.
      const revisionId =
        scenario.current_revision_id ?? scenario.revisions.at(-1)?.revision_id ?? null
      if (!revisionId) {
        throw new Error('이 시나리오에는 리비전이 없습니다.')
      }
      const revision = await api.getRevisionContent(revisionId)
      onLoadDraft(
        draftFromContent(revision.content, { scenarioId: scenario.scenario_id, name: scenario.name }),
        { switch: true },
      )
      const draftNote =
        scenario.current_revision_id == null ? ' (초안 리비전 — 저장하면 게시됩니다)' : ''
      setStatus(`불러옴: ${scenario.name}${draftNote} (필드 복원됨 — 실행하면 결과가 재현됩니다)`)
    } catch (e) {
      setError(describe(e))
    } finally {
      setBusy(false)
    }
  }

  const clone = async (pointer: SavedScenarioPointer) => {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      const scenario = await api.getScenario(pointer.scenarioId)
      const sourceRevisionId =
        scenario.current_revision_id ?? scenario.revisions.at(-1)?.revision_id ?? null
      if (!sourceRevisionId) throw new Error('복제할 리비전이 없습니다.')
      const cloned = await api.cloneScenarioRevision(sourceRevisionId, {
        stable_key: genStableKey(),
        name: `${scenario.name} (사본)`,
      })
      setPointers(
        addPointer({
          scenarioId: cloned.scenario_id,
          stableKey: cloned.stable_key,
          name: cloned.name,
          savedAt: new Date().toISOString(),
        }),
      )
      setStatus(`복제됨: ${cloned.name}. 원본 게시 리비전은 변경되지 않았습니다.`)
    } catch (e) {
      setError(describe(e))
    } finally {
      setBusy(false)
    }
  }

  // Load one of the two built-in scenarios (they behave like saved scenarios in this list; their
  // content ships with the app, so no server round-trip is needed to open them).
  const loadBuiltin = (preset: PresetDescriptor) => {
    if (
      unsaved &&
      !window.confirm('저장되지 않은 변경이 있습니다. 다른 시나리오를 불러오면 현재 편집 내용이 사라질 수 있습니다. 계속할까요?')
    ) {
      return
    }
    onLoadDraft(draftFromPreset(preset), { switch: true })
  }

  return (
    <fieldset className="card">
      <legend>{mode === 'save' ? '시나리오 저장' : '시나리오 열기 · 최근'}</legend>
      {mode === 'save' ? (
        <p className="hint">서버에 저장됩니다. 브라우저에는 시나리오 ID만 기억하며 내용은 저장하지 않습니다.</p>
      ) : null}

      {mode === 'save' ? (
        <>
          <div className="library-actions">
            <button type="button" className="btn btn--primary" onClick={saveNew} disabled={busy}>
              새 시나리오로 저장
            </button>
            {draft.savedScenarioId ? (
              <button type="button" className="btn btn--secondary" onClick={saveRevision} disabled={busy}>
                현재 시나리오에 새 리비전으로 저장
              </button>
            ) : null}
          </div>

          {saveScopeWarnings(draft).length > 0 ? (
            <div className="hint hint--warn" role="status">
              저장 범위 안내: 저장은 실행 가능한 스냅샷(현재 활성 입력)을 보관합니다.
              <ul className="save-scope-warnings">
                {saveScopeWarnings(draft).map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      ) : null}

      {status ? <p className="hint" role="status">{status}</p> : null}
      {error ? (
        <StatusPanel kind="error" title="시나리오 작업 실패">
          {error}
        </StatusPanel>
      ) : null}

      {mode === 'open' ? (
        <ul className="library-list">
          {PRESETS.map((p) => (
            <li key={p.fixtureId} className="library-item">
              <div>
                <span>{p.title}</span>
              </div>
              <div className="library-item__actions">
                <button
                  type="button"
                  className="btn btn--link"
                  onClick={() => loadBuiltin(p)}
                  disabled={busy}
                  aria-label={`${p.title} 불러오기`}
                >
                  불러오기
                </button>
              </div>
            </li>
          ))}
          {pointers.map((p) => (
            <li key={p.scenarioId} className="library-item">
              <div>
                <span>{p.name}</span>
                <span className="hint mono"> · {p.scenarioId.slice(0, 8)}…</span>
              </div>
              <div className="library-item__actions">
                <button type="button" className="btn btn--link" onClick={() => load(p)} disabled={busy}>
                  불러오기
                </button>
                <button type="button" className="btn btn--link" onClick={() => clone(p)} disabled={busy}>
                  복제
                </button>
                <button
                  type="button"
                  className="btn btn--link"
                  onClick={() => forgetPointer(p.scenarioId)}
                  title="로컬 목록에서만 제거"
                >
                  제거
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </fieldset>
  )
}
