import { useState } from 'react'

import { api, ApiError, NetworkError } from '../../shared/api/client'
import type { OrbitSpecDTO, SatellitePresetPayload } from '../../shared/api/types'
import { orbitSpecFromForm, type OrbitForm } from '../scenario/draft'
import { PRESETS } from '../scenario/presets'
import { OrbitInputForm } from '../scenario/OrbitInputForm'
import { Modal } from '../../shared/ui/Modal'
import { StatusPanel } from '../../shared/ui/StatusPanel'
import {
  addSatellitePointer,
  loadSatellitePointers,
  removeSatellitePointer,
  type SavedSatellitePointer,
} from './storage'

export interface SatelliteLibraryProps {
  /** Load a saved satellite into the current scenario (orbit + name only; stations/cart/window kept). */
  onApply: (payload: SatellitePresetPayload) => void
}

// Bundled example satellites, from the shipped scenarios (name + orbit), de-duplicated by name since
// scenarios may share a satellite (e.g. Landsat-9). Loading one applies its orbit/name to the scenario.
const BUILTIN_SATELLITES: { name: string; payload: SatellitePresetPayload }[] = (() => {
  const seen = new Set<string>()
  const out: { name: string; payload: SatellitePresetPayload }[] = []
  for (const p of PRESETS) {
    if (!p.content.orbit) continue
    const name = p.satelliteName ?? p.title
    if (seen.has(name)) continue
    seen.add(name)
    out.push({
      name,
      payload: {
        schema: 'passbudget-satellite-preset-1',
        name,
        provenance: p.provenance,
        isAssumption: true,
        orbit: p.content.orbit as OrbitSpecDTO,
      },
    })
  }
  return out
})()

/** A blank orbit form for the "새 위성 등록" modal — values start empty (shown as placeholder hints). */
const EMPTY_ORBIT: OrbitForm = {
  mode: 'TWO_BODY_V1',
  epoch: '',
  semiMajorAxisMm: '',
  eccentricityPpb: '',
  inclinationUdeg: '',
  raanUdeg: '',
  argumentOfPerigeeUdeg: '',
  trueAnomalyUdeg: '',
  muM3PerS2: '',
  tleLine1: '',
  tleLine2: '',
}

function genStableKey(): string {
  const ts = new Date().toISOString().replace(/[^0-9]/g, '').slice(0, 14)
  const rand = Math.random().toString(36).slice(2, 8)
  return `SAT-${ts}-${rand}`
}

function isSatellitePayload(value: unknown): value is SatellitePresetPayload {
  return (
    typeof value === 'object' &&
    value !== null &&
    (value as { schema?: unknown }).schema === 'passbudget-satellite-preset-1' &&
    typeof (value as { orbit?: unknown }).orbit === 'object'
  )
}

/**
 * The saved-satellite library shown in a side panel: a name-only list of server-saved satellites to
 * load, plus a "새 위성 등록" button that opens a modal to enter a new satellite and 저장 it. Saving
 * always creates a NEW saved satellite (a fresh SPACECRAFT profile; SQLite-persistent). Only pointers
 * (profile id + name) are bookmarked locally; the payload is read from the server on load.
 */
export function SatelliteLibrary({ onApply }: SatelliteLibraryProps) {
  const [pointers, setPointers] = useState<SavedSatellitePointer[]>(() => loadSatellitePointers())
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Register-modal state (starts blank; example values show as placeholder hints).
  const [modalOpen, setModalOpen] = useState(false)
  const [formName, setFormName] = useState('')
  const [formOrbit, setFormOrbit] = useState<OrbitForm>(EMPTY_ORBIT)

  const describe = (e: unknown): string => {
    if (e instanceof ApiError) {
      if (e.status === 404) {
        return `${e.message} 서버에 이 위성이 없습니다(백엔드가 재시작되었을 수 있습니다). “제거”로 정리하세요.`
      }
      return `[${e.code}] ${e.message}`
    }
    if (e instanceof NetworkError) return e.message
    return (e as Error).message
  }

  const openModal = () => {
    setFormName('')
    setFormOrbit(EMPTY_ORBIT)
    setError(null)
    setModalOpen(true)
  }

  const save = async () => {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      const name = formName.trim() || '위성'
      const payload: SatellitePresetPayload = {
        schema: 'passbudget-satellite-preset-1',
        name,
        provenance: '',
        isAssumption: true,
        orbit: orbitSpecFromForm(formOrbit), // throws on invalid input → surfaced below
      }
      const stableKey = genStableKey()
      const profile = await api.createProfile({
        stable_key: stableKey,
        kind: 'SPACECRAFT',
        name,
        is_preset: true,
      })
      const revision = await api.createProfileRevision(profile.profile_id, { label: 'v1', payload })
      await api.publishProfileRevision(revision.revision_id)
      setPointers(
        addSatellitePointer({
          profileId: profile.profile_id,
          stableKey,
          name,
          savedAt: new Date().toISOString(),
        }),
      )
      setModalOpen(false)
      setStatus(`저장됨: ${name}`)
    } catch (e) {
      setError(describe(e))
    } finally {
      setBusy(false)
    }
  }

  const load = async (pointer: SavedSatellitePointer) => {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      const profile = await api.getProfile(pointer.profileId)
      const revisionId = profile.current_revision_id
      if (!revisionId) throw new Error('이 위성에는 게시된 버전이 없습니다.')
      const content = await api.getProfileRevisionContent(revisionId)
      if (!isSatellitePayload(content.payload)) throw new Error('위성 형식이 아닙니다.')
      onApply(content.payload)
      setStatus(`불러옴: ${profile.name} — 이 시나리오의 위성만 교체됩니다.`)
    } catch (e) {
      setError(describe(e))
    } finally {
      setBusy(false)
    }
  }

  const forget = (profileId: string) => {
    setPointers(removeSatellitePointer(profileId))
    setStatus('로컬 목록에서 제거했습니다 (서버 데이터는 변경하지 않았습니다).')
  }

  return (
    <div className="library-panel">
      {status ? <p className="hint" role="status">{status}</p> : null}
      {error && !modalOpen ? (
        <StatusPanel kind="error" title="위성 작업 실패">{error}</StatusPanel>
      ) : null}

      <ul className="namelist">
        {pointers.map((p) => (
          <li key={p.profileId} className="namelist__row">
            <button
              type="button"
              className="namelist__name"
              onClick={() => load(p)}
              disabled={busy}
              title="이 위성을 현재 시나리오에 불러오기"
            >
              {p.name}
            </button>
            <button
              type="button"
              className="namelist__remove"
              onClick={() => forget(p.profileId)}
              title="로컬 목록에서만 제거"
              aria-label={`${p.name} 목록에서 제거`}
            >
              ✕
            </button>
          </li>
        ))}
        {BUILTIN_SATELLITES.map((s) => (
          <li key={s.name} className="namelist__row">
            <button
              type="button"
              className="namelist__name"
              onClick={() => onApply(s.payload)}
              disabled={busy}
              title="이 위성을 현재 시나리오에 불러오기"
            >
              {s.name}
            </button>
          </li>
        ))}
      </ul>

      <button type="button" className="btn btn--primary library-panel__add" onClick={openModal}>
        ＋ 새 위성 등록
      </button>

      {modalOpen ? (
        <Modal
          title="새 위성 등록"
          onClose={() => setModalOpen(false)}
          footer={
            <>
              <button type="button" className="btn btn--secondary" onClick={() => setModalOpen(false)} disabled={busy}>
                취소
              </button>
              <button type="button" className="btn btn--primary" onClick={save} disabled={busy}>
                저장
              </button>
            </>
          }
        >
          <div className="unit-field">
            <label htmlFor="sat-reg-name">위성 이름</label>
            <input
              id="sat-reg-name"
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              placeholder="예: Sentinel-2 위성"
            />
          </div>
          <OrbitInputForm orbit={formOrbit} patch={(partial) => setFormOrbit((o) => ({ ...o, ...partial }))} />
          {error ? <StatusPanel kind="error" title="저장 실패">{error}</StatusPanel> : null}
        </Modal>
      ) : null}
    </div>
  )
}
