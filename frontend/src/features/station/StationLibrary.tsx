import { useState } from 'react'

import { api, ApiError, NetworkError } from '../../shared/api/client'
import type { GroundStationPresetPayload, StationDTO } from '../../shared/api/types'
import { stationDtoFromForm, stationFormFromDto, type StationForm } from '../scenario/draft'
import { PRESETS } from '../scenario/presets'
import { GroundStationEditor } from '../scenario/GroundStationList'
import { Modal } from '../../shared/ui/Modal'
import { StatusPanel } from '../../shared/ui/StatusPanel'
import {
  addStationPointer,
  loadStationPointers,
  removeStationPointer,
  type SavedStationPointer,
} from './storage'

export interface StationLibraryProps {
  /** Add a station DTO into the current scenario (the shell re-keys it if the key already exists). */
  onAddStation: (station: StationDTO) => void
}

// Bundled example stations, flattened from the shipped scenarios (name = stable key), de-duplicated by
// stable key since scenarios may share a station (e.g. 국민대).
const BUILTIN_STATIONS: StationDTO[] = (() => {
  const seen = new Set<string>()
  const out: StationDTO[] = []
  for (const p of PRESETS) {
    for (const s of p.content.stations) {
      if (!seen.has(s.stable_key)) {
        seen.add(s.stable_key)
        out.push(s)
      }
    }
  }
  return out
})()

function genProfileKey(): string {
  const ts = new Date().toISOString().replace(/[^0-9]/g, '').slice(0, 14)
  const rand = Math.random().toString(36).slice(2, 8)
  return `GSP-${ts}-${rand}`
}

function isStationPayload(value: unknown): value is GroundStationPresetPayload {
  return (
    typeof value === 'object' &&
    value !== null &&
    (value as { schema?: unknown }).schema === 'passbudget-ground-station-preset-1' &&
    typeof (value as { station?: unknown }).station === 'object'
  )
}

/**
 * The ground-station library shown in a side panel: name-only lists of built-in example stations and
 * server-saved stations, each addable to the current scenario, plus a "새 지상국 등록" modal to enter a
 * new station and 저장 it. Saving always creates a NEW saved station (a fresh GROUND_STATION profile;
 * SQLite-persistent) and also adds it to the scenario. Only pointers are bookmarked locally.
 */
export function StationLibrary({ onAddStation }: StationLibraryProps) {
  const [pointers, setPointers] = useState<SavedStationPointer[]>(() => loadStationPointers())
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [modalOpen, setModalOpen] = useState(false)
  const [formName, setFormName] = useState('')
  const [formStation, setFormStation] = useState<StationForm | null>(null)

  const describe = (e: unknown): string => {
    if (e instanceof ApiError) {
      if (e.status === 404) {
        return `${e.message} 서버에 이 지상국이 없습니다(백엔드가 재시작되었을 수 있습니다). “제거”로 정리하세요.`
      }
      return `[${e.code}] ${e.message}`
    }
    if (e instanceof NetworkError) return e.message
    return (e as Error).message
  }

  const openModal = () => {
    // Start with empty fields (example values show as placeholder hints). The base is a valid built-in
    // station so advanced passthrough capacity fields exist; the visible editable leaves are cleared.
    const seed = stationFormFromDto(structuredClone(BUILTIN_STATIONS[0]))
    setFormStation({
      ...seed,
      stableKey: '',
      preferenceRank: '',
      latitudeUdeg: '',
      longitudeEastUdeg: '',
      ellipsoidalHeightMm: '',
      minimumElevationUdeg: '',
      rateNumeratorBits: '',
      rateDenominatorSeconds: '',
      efficiencyNumerator: '',
      efficiencyDenominator: '',
    })
    setFormName('')
    setError(null)
    setModalOpen(true)
  }

  const save = async () => {
    if (!formStation) return
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      const station = stationDtoFromForm(formStation) // throws on invalid input → surfaced below
      const name = formName.trim() || station.stable_key
      const payload: GroundStationPresetPayload = {
        schema: 'passbudget-ground-station-preset-1',
        name,
        station,
      }
      const stableKey = genProfileKey()
      const profile = await api.createProfile({
        stable_key: stableKey,
        kind: 'GROUND_STATION',
        name,
        is_preset: true,
      })
      const revision = await api.createProfileRevision(profile.profile_id, { label: 'v1', payload })
      await api.publishProfileRevision(revision.revision_id)
      setPointers(
        addStationPointer({
          profileId: profile.profile_id,
          stableKey,
          name,
          savedAt: new Date().toISOString(),
        }),
      )
      onAddStation(station)
      setModalOpen(false)
      setStatus(`저장됨: ${name} (현재 시나리오에도 추가함)`)
    } catch (e) {
      setError(describe(e))
    } finally {
      setBusy(false)
    }
  }

  const loadSaved = async (pointer: SavedStationPointer) => {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      const profile = await api.getProfile(pointer.profileId)
      const revisionId = profile.current_revision_id
      if (!revisionId) throw new Error('이 지상국에는 게시된 버전이 없습니다.')
      const content = await api.getProfileRevisionContent(revisionId)
      if (!isStationPayload(content.payload)) throw new Error('지상국 형식이 아닙니다.')
      onAddStation(content.payload.station)
      setStatus(`추가함: ${profile.name}`)
    } catch (e) {
      setError(describe(e))
    } finally {
      setBusy(false)
    }
  }

  const forget = (profileId: string) => {
    setPointers(removeStationPointer(profileId))
    setStatus('로컬 목록에서 제거했습니다 (서버 데이터는 변경하지 않았습니다).')
  }

  return (
    <div className="library-panel">
      {status ? <p className="hint" role="status">{status}</p> : null}
      {error && !modalOpen ? (
        <StatusPanel kind="error" title="지상국 작업 실패">{error}</StatusPanel>
      ) : null}

      <ul className="namelist">
        {pointers.map((p) => (
          <li key={p.profileId} className="namelist__row">
            <button
              type="button"
              className="namelist__name"
              onClick={() => loadSaved(p)}
              disabled={busy}
              title="이 지상국을 현재 시나리오에 추가"
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
        {BUILTIN_STATIONS.map((s) => (
          <li key={s.stable_key} className="namelist__row">
            <button
              type="button"
              className="namelist__name mono"
              onClick={() => onAddStation(s)}
              disabled={busy}
              title="이 지상국을 현재 시나리오에 추가"
            >
              {s.stable_key}
            </button>
          </li>
        ))}
      </ul>

      <button type="button" className="btn btn--primary library-panel__add" onClick={openModal}>
        ＋ 새 지상국 등록
      </button>

      {modalOpen && formStation ? (
        <Modal
          title="새 지상국 등록"
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
            <label htmlFor="gs-reg-name">이름</label>
            <input
              id="gs-reg-name"
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              placeholder="예: 서울 지상국"
            />
          </div>
          <GroundStationEditor
            station={formStation}
            onPatch={(partial) => setFormStation((s) => (s ? { ...s, ...partial } : s))}
          />
          {error ? <StatusPanel kind="error" title="저장 실패">{error}</StatusPanel> : null}
        </Modal>
      ) : null}
    </div>
  )
}
