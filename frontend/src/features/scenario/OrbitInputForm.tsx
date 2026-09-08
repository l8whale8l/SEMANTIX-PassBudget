import type { OrbitForm } from './draft'
import { UnitField } from '../../shared/ui/UnitField'
import type { EvidenceControl } from '../../shared/ui/evidence'

export interface OrbitInputFormProps {
  orbit: OrbitForm
  patch: (partial: Partial<OrbitForm>) => void
  /** Optional per-field measured/assumption marks (display only; never affects the calculation). */
  evidence?: EvidenceControl
}

export function OrbitInputForm({ orbit, patch, evidence }: OrbitInputFormProps) {
  // Wire a field's evidence dot by key; a no-op when no control is supplied.
  const ev = (field: string) =>
    evidence
      ? { evidence: evidence.get(`orbit:${field}`), onCycleEvidence: () => evidence.cycle(`orbit:${field}`) }
      : {}
  return (
    <fieldset className="card">
      <legend>궤도 입력</legend>
      <div className="orbit-mode" role="radiogroup" aria-label="궤도 입력 모드">
        <label>
          <input
            type="radio"
            name="orbit-mode"
            checked={orbit.mode === 'TWO_BODY_V1'}
            onChange={() => patch({ mode: 'TWO_BODY_V1' })}
          />
          가상 궤도 (two-body)
        </label>
        <label>
          <input
            type="radio"
            name="orbit-mode"
            checked={orbit.mode === 'GP_TLE'}
            onChange={() => patch({ mode: 'GP_TLE' })}
          />
          TLE 직접 입력
        </label>
      </div>

      {orbit.mode === 'TWO_BODY_V1' ? (
        <>
          <UnitField
            label="epoch"
            unit="UTC"
            monospace
            value={orbit.epoch}
            onChange={(v) => patch({ epoch: v })}
            placeholder="예: 2026-09-03T00:00:00Z"
            {...ev('epoch')}
          />
          <div className="row">
            <UnitField
              label="장반경"
              unit="mm"
              help="궤도 장반경(mm). 위성 고도와 동일하지 않습니다."
              inputMode="numeric"
              value={orbit.semiMajorAxisMm}
              onChange={(v) => patch({ semiMajorAxisMm: v })}
              placeholder="예: 7078137000"
              {...ev('semiMajorAxisMm')}
            />
            <UnitField
              label="이심률"
              unit="ppb"
              inputMode="numeric"
              value={orbit.eccentricityPpb}
              onChange={(v) => patch({ eccentricityPpb: v })}
              placeholder="예: 0"
              {...ev('eccentricityPpb')}
            />
          </div>
          <div className="row">
            <UnitField
              label="경사각"
              unit="μdeg"
              inputMode="numeric"
              value={orbit.inclinationUdeg}
              onChange={(v) => patch({ inclinationUdeg: v })}
              placeholder="예: 98000000"
              {...ev('inclinationUdeg')}
            />
            <UnitField
              label="RAAN"
              unit="μdeg"
              inputMode="numeric"
              value={orbit.raanUdeg}
              onChange={(v) => patch({ raanUdeg: v })}
              placeholder="예: 90000000"
              {...ev('raanUdeg')}
            />
          </div>
          <div className="row">
            <UnitField
              label="근지점 편각"
              unit="μdeg"
              inputMode="numeric"
              value={orbit.argumentOfPerigeeUdeg}
              onChange={(v) => patch({ argumentOfPerigeeUdeg: v })}
              placeholder="예: 0"
              {...ev('argumentOfPerigeeUdeg')}
            />
            <UnitField
              label="진근점 이각"
              unit="μdeg"
              inputMode="numeric"
              value={orbit.trueAnomalyUdeg}
              onChange={(v) => patch({ trueAnomalyUdeg: v })}
              placeholder="예: 0"
              {...ev('trueAnomalyUdeg')}
            />
          </div>
          <UnitField
            label="중력상수 μ"
            unit="m³/s²"
            inputMode="numeric"
            value={orbit.muM3PerS2}
            onChange={(v) => patch({ muM3PerS2: v })}
            placeholder="예: 398600441500000"
            {...ev('muM3PerS2')}
          />
        </>
      ) : (
        <>
          <p className="hint">
            TLE 각 줄은 정확히 69자여야 합니다. 원문 공백을 유지하세요. 비공개 실제 TLE를
            입력하지 마세요 — 입력은 요청 데이터일 뿐 실제 비행 성능 주장이 아닙니다.
          </p>
          <UnitField
            label="TLE line 1"
            monospace
            value={orbit.tleLine1}
            help={`현재 ${orbit.tleLine1.length}자`}
            onChange={(v) => patch({ tleLine1: v })}
            {...ev('tleLine1')}
          />
          <UnitField
            label="TLE line 2"
            monospace
            value={orbit.tleLine2}
            help={`현재 ${orbit.tleLine2.length}자`}
            onChange={(v) => patch({ tleLine2: v })}
            {...ev('tleLine2')}
          />
        </>
      )}
    </fieldset>
  )
}
