import { useState } from 'react'

import { type OrbitForm, type ScenarioDraft } from './draft'
import { OrbitInputForm } from './OrbitInputForm'
import { Modal } from '../../shared/ui/Modal'
import { EvidenceLegend } from '../../shared/ui/EvidenceLegend'
import {
  countMarks,
  ORBIT_TLE_FIELDS,
  ORBIT_TWO_BODY_FIELDS,
  type EvidenceControl,
} from '../../shared/ui/evidence'

export interface SatellitePanelProps {
  draft: ScenarioDraft
  /** Patch UI-only satellite metadata (name) on the draft. */
  patch: (partial: Partial<ScenarioDraft>) => void
  patchOrbit: (partial: Partial<OrbitForm>) => void
  /** Open the saved-satellite library (a side panel: load a saved satellite or 새 위성 등록). */
  onOpenLibrary: () => void
  /** Per-field measured/assumption marks for the orbit (display only; never affects the calc). */
  evidence?: EvidenceControl
}

/**
 * The satellite tab: a SINGLE satellite (one orbit, many ground stations). It SHOWS which satellite is
 * currently selected (its name); the ✎ button opens an edit dialog to change the name/orbit of the
 * current scenario satellite (with the same per-field measured/assumption marks as elsewhere), and
 * 불러오기 opens the library (load a saved satellite, or 새 위성 등록 to enter one).
 */
export function SatellitePanel({ draft, patch, patchOrbit, onOpenLibrary, evidence }: SatellitePanelProps) {
  const [editOpen, setEditOpen] = useState(false)
  const orbit = draft.orbit
  const orbitKeys = (orbit.mode === 'GP_TLE' ? ORBIT_TLE_FIELDS : ORBIT_TWO_BODY_FIELDS).map(
    (f) => `orbit:${f}`,
  )

  return (
    <div className="satpanel">
      <div className="satpanel__summary">
        <div>
          <h4 className="satpanel__title">현재 위성</h4>
          <p className="satpanel__meta">{draft.satelliteName || '위성'}</p>
        </div>
        <div className="satpanel__actions">
          <button
            type="button"
            className="btn-icon"
            onClick={() => setEditOpen(true)}
            title="위성 정보 편집 (이름·궤도)"
            aria-label="위성 정보 편집"
          >
            ✎
          </button>
          <button type="button" className="btn btn--secondary" onClick={onOpenLibrary}>
            불러오기
          </button>
        </div>
      </div>

      {editOpen ? (
        <Modal
          title="위성 정보 편집"
          onClose={() => setEditOpen(false)}
          footer={
            <button type="button" className="btn btn--primary" onClick={() => setEditOpen(false)}>
              완료
            </button>
          }
        >
          <div className="unit-field">
            <label htmlFor="sat-edit-name">위성 이름</label>
            <input
              id="sat-edit-name"
              value={draft.satelliteName}
              onChange={(e) => patch({ satelliteName: e.target.value })}
              placeholder="예: Sentinel-2 위성"
            />
          </div>
          {evidence ? <EvidenceLegend counts={countMarks(evidence.get, orbitKeys)} /> : null}
          <OrbitInputForm orbit={orbit} patch={patchOrbit} evidence={evidence} />
        </Modal>
      ) : null}
    </div>
  )
}
