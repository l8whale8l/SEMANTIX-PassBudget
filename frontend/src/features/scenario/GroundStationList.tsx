import type { StationForm } from './draft'
import { UnitField } from '../../shared/ui/UnitField'
import { FriendlyField } from '../../shared/ui/FriendlyField'
import { EvidenceLegend } from '../../shared/ui/EvidenceLegend'
import { countMarks, STATION_FIELDS, type EvidenceControl } from '../../shared/ui/evidence'
import {
  degToUdeg,
  efficiencyToPct,
  mbpsToRate,
  mmToM,
  mToMm,
  pctToEfficiency,
  rateToMbps,
  udegToDeg,
} from '../../shared/format/friendly'

export interface GroundStationListProps {
  stations: StationForm[]
  patchStation: (editId: string, partial: Partial<StationForm>) => void
  removeStation: (editId: string) => void
  /** Map-visibility state (screen only — never affects the calculation or hash). */
  hiddenStationKeys: ReadonlySet<string>
  onToggleHidden: (stableKey: string) => void
  /** Open the saved-station library side panel (예시/저장된 지상국 목록 + 새 지상국 등록). */
  onOpenLibrary: () => void
  /** Controlled selection so the left sidebar can open a specific station's detail here. */
  selectedEditId: string | null
  onSelectEditId: (editId: string | null) => void
}

const isIntStr = (s: string) => /^-?\d+$/.test(s.trim())

/**
 * The ground-station list with a separate detail editor (spec §5). Each row carries the two clearly
 * distinct controls: a “계산” checkbox (a real scenario input — toggling it changes the run and marks
 * 재계산 필요) and a “지도” eye toggle (screen-only visibility — it never touches the hash or result).
 * Selecting a row opens that station's detail editor below the list; only one station's fields show at
 * a time, instead of every station's form stacked. New stations are added blank or copied from a
 * preset (the preset itself is never mutated).
 */
export function GroundStationList(props: GroundStationListProps) {
  const { stations, patchStation, removeStation, hiddenStationKeys, onToggleHidden, onOpenLibrary } = props
  const selectedId = props.selectedEditId
  const setSelectedId = props.onSelectEditId
  const activeCount = stations.filter((s) => s.active).length

  const handleRemove = (editId: string) => {
    removeStation(editId)
    if (selectedId === editId) setSelectedId(null)
  }

  return (
    <fieldset className="card">
      <legend>지상국 ({activeCount}/{stations.length} 계산 포함)</legend>
      {activeCount === 0 ? (
        <p className="hint hint--warn" role="alert">
          계산에 포함된 지상국이 없습니다. 초안은 보존되지만 이 상태로는 실행할 수 없습니다 — 최소 한 곳을
          “계산”에 포함하세요.
        </p>
      ) : null}

      <ul className="stationrows">
        {stations.map((s) => {
          const shownOnMap = !hiddenStationKeys.has(s.stableKey)
          return (
            <li
              key={s.editId}
              className={
                'stationrow' +
                (s.active ? '' : ' stationrow--inactive') +
                (s.editId === selectedId ? ' stationrow--selected' : '')
              }
            >
              <label className="stationrow__calc" title="계산에 포함 — 변경하면 재계산이 필요합니다">
                <input
                  type="checkbox"
                  checked={s.active}
                  onChange={(e) => patchStation(s.editId, { active: e.target.checked })}
                />
                <span className="sr-only">계산에 포함</span>
              </label>
              <button
                type="button"
                className="stationrow__name mono"
                onClick={() => setSelectedId(s.editId)}
                aria-expanded={s.editId === selectedId}
                title="편집 — 상세 패널 열기"
              >
                {s.stableKey}
              </button>
              <button
                type="button"
                className={shownOnMap ? 'stationrow__eye' : 'stationrow__eye stationrow__eye--off'}
                onClick={() => onToggleHidden(s.stableKey)}
                aria-pressed={shownOnMap}
                title={shownOnMap ? '지도에서 숨기기 (표시만, 계산 불변)' : '지도에 표시 (표시만, 계산 불변)'}
              >
                {shownOnMap ? '👁' : '🚫'}
                <span className="sr-only">지도 표시 전환</span>
              </button>
              <button
                type="button"
                className="stationrow__remove"
                onClick={() => handleRemove(s.editId)}
                disabled={stations.length <= 1}
                title={stations.length <= 1 ? '마지막 지상국은 제거할 수 없습니다' : '제거'}
              >
                ✕<span className="sr-only">제거</span>
              </button>
            </li>
          )
        })}
      </ul>

      <div className="stationrows__add">
        <button type="button" className="btn btn--secondary" onClick={onOpenLibrary}>
          ＋ 새 지상국
        </button>
      </div>

      <p className="hint">
        “＋ 새 지상국”을 누르면 옆에 저장된·예시 지상국 목록이 열립니다. 이름을 누르면 오른쪽에 상세 편집
        창이 열립니다.
      </p>
    </fieldset>
  )
}

export interface GroundStationEditorProps {
  station: StationForm
  onPatch: (partial: Partial<StationForm>) => void
  /** Optional per-field measured/assumption marks (display only; never affects the calculation). */
  evidence?: EvidenceControl
}

/** The per-station detail editor, shown in a companion panel beside the list (not inline). */
export function GroundStationEditor({ station, onPatch, evidence }: GroundStationEditorProps) {
  const rateCanonical = `${station.rateNumeratorBits}/${station.rateDenominatorSeconds}`
  const effCanonical = `${station.efficiencyNumerator}/${station.efficiencyDenominator}`
  // Wire a field's evidence dot by key, scoped to this station's stable key so marks are per-station
  // and survive across sessions. Advanced exact fields reuse the same key as their friendly twin, so
  // a single value carries one mark regardless of which control edits it. No-op without a control.
  const ev = (field: string) =>
    evidence
      ? {
          evidence: evidence.get(`station:${station.stableKey}:${field}`),
          onCycleEvidence: () => evidence.cycle(`station:${station.stableKey}:${field}`),
        }
      : {}

  return (
    <div className={`station-detail${station.active ? '' : ' station-detail--inactive'}`}>
      <div className="station-detail__head">
        <h4 className="station-detail__title">지상국 상세 — <span className="mono">{station.stableKey}</span></h4>
        {!station.active ? <span className="hint">계산에서 제외됨 (편집은 가능)</span> : null}
      </div>
      {evidence ? (
        <EvidenceLegend
          counts={countMarks(evidence.get, STATION_FIELDS.map((f) => `station:${station.stableKey}:${f}`))}
        />
      ) : null}
      <div className="row">
        <UnitField
          label="stable key"
          monospace
          value={station.stableKey}
          onChange={(v) => onPatch({ stableKey: v })}
          placeholder="예: SYN-GS-01"
        />
        <UnitField
          label="선호 순위"
          unit="preference_rank"
          inputMode="numeric"
          value={station.preferenceRank}
          onChange={(v) => onPatch({ preferenceRank: v })}
          placeholder="예: 1"
          {...ev('preferenceRank')}
        />
      </div>

      <div className="row">
        <FriendlyField
          label="위도"
          unit="°"
          help="북위 양수. 내부적으로 μdeg 정수로 저장됩니다."
          canonical={station.latitudeUdeg}
          toFriendly={(c) => (isIntStr(c) ? udegToDeg(Number(c)) : null)}
          commit={(t) => onPatch({ latitudeUdeg: String(degToUdeg('위도', t)) })}
          placeholder="예: 37.61"
          {...ev('latitudeUdeg')}
        />
        <FriendlyField
          label="경도(동경)"
          unit="°"
          help="동경 양수."
          canonical={station.longitudeEastUdeg}
          toFriendly={(c) => (isIntStr(c) ? udegToDeg(Number(c)) : null)}
          commit={(t) => onPatch({ longitudeEastUdeg: String(degToUdeg('경도', t)) })}
          placeholder="예: 126.99"
          {...ev('longitudeEastUdeg')}
        />
      </div>
      <div className="row">
        <FriendlyField
          label="타원체 고도"
          unit="m"
          help="WGS-84 타원체 고도. 해발고도(정표고)와 다릅니다."
          canonical={station.ellipsoidalHeightMm}
          toFriendly={(c) => (isIntStr(c) ? mmToM(Number(c)) : null)}
          commit={(t) => onPatch({ ellipsoidalHeightMm: String(mToMm('고도', t)) })}
          placeholder="예: 120"
          {...ev('ellipsoidalHeightMm')}
        />
        <FriendlyField
          label="최소 앙각"
          unit="°"
          canonical={station.minimumElevationUdeg}
          toFriendly={(c) => (isIntStr(c) ? udegToDeg(Number(c)) : null)}
          commit={(t) => onPatch({ minimumElevationUdeg: String(degToUdeg('최소 앙각', t)) })}
          placeholder="예: 5"
          {...ev('minimumElevationUdeg')}
        />
      </div>

      <div className="station-card__link">
        <span className="station-card__link-title">통신 가정 (capacity)</span>
        <div className="row">
          <FriendlyField
            label="다운링크 속도"
            unit="Mbps"
            help="1 Mbps = 1,000,000 bits/s. 내부적으로 유리수 bits/s로 저장됩니다."
            canonical={rateCanonical}
            toFriendly={(c) => {
              const [n, d] = c.split('/')
              return isIntStr(n) && isIntStr(d) ? rateToMbps(Number(n), Number(d)) : null
            }}
            commit={(t) => {
              const f = mbpsToRate('속도', t)
              onPatch({
                rateNumeratorBits: String(f.numerator),
                rateDenominatorSeconds: String(f.denominator),
              })
            }}
            placeholder="예: 100"
            {...ev('rate')}
          />
          <FriendlyField
            label="유효율"
            unit="%"
            help="active_efficiency. 이미 반영된 효과와 중복 적용하지 마세요."
            canonical={effCanonical}
            toFriendly={(c) => {
              const [n, d] = c.split('/')
              return isIntStr(n) && isIntStr(d) ? efficiencyToPct(Number(n), Number(d)) : null
            }}
            commit={(t) => {
              const f = pctToEfficiency('유효율', t)
              onPatch({
                efficiencyNumerator: String(f.numerator),
                efficiencyDenominator: String(f.denominator),
              })
            }}
            placeholder="예: 90"
            {...ev('efficiency')}
          />
        </div>
        <p className="hint">
          근거 등급 {station.base.capacity.evidence_state ?? 'UNKNOWN'} · 가드/리저브/측정점/근거 등
          기타 고급 필드는 원래 값 그대로 보존됩니다.
        </p>
      </div>

      <details className="station-advanced">
        <summary>고급 (정확 정수·유리수)</summary>
        <p className="hint">
          위 친화 단위로 정확히 표현하기 어려운 값은 여기서 원본 정수·유리수로 직접 편집합니다.
        </p>
        <div className="row">
          <UnitField
            label="위도 μdeg"
            unit="degree×1e6"
            inputMode="numeric"
            monospace
            value={station.latitudeUdeg}
            onChange={(v) => onPatch({ latitudeUdeg: v })}
            {...ev('latitudeUdeg')}
          />
          <UnitField
            label="경도 μdeg"
            unit="degree×1e6"
            inputMode="numeric"
            monospace
            value={station.longitudeEastUdeg}
            onChange={(v) => onPatch({ longitudeEastUdeg: v })}
            {...ev('longitudeEastUdeg')}
          />
        </div>
        <div className="row">
          <UnitField
            label="타원체 고도 mm"
            unit="m×1000"
            inputMode="numeric"
            monospace
            value={station.ellipsoidalHeightMm}
            onChange={(v) => onPatch({ ellipsoidalHeightMm: v })}
            {...ev('ellipsoidalHeightMm')}
          />
          <UnitField
            label="최소 앙각 μdeg"
            unit="degree×1e6"
            inputMode="numeric"
            monospace
            value={station.minimumElevationUdeg}
            onChange={(v) => onPatch({ minimumElevationUdeg: v })}
            {...ev('minimumElevationUdeg')}
          />
        </div>
        <div className="row">
          <UnitField
            label="속도 분자"
            unit="bits"
            inputMode="numeric"
            monospace
            value={station.rateNumeratorBits}
            onChange={(v) => onPatch({ rateNumeratorBits: v })}
            {...ev('rate')}
          />
          <UnitField
            label="속도 분모"
            unit="seconds"
            inputMode="numeric"
            monospace
            value={station.rateDenominatorSeconds}
            onChange={(v) => onPatch({ rateDenominatorSeconds: v })}
            {...ev('rate')}
          />
        </div>
        <div className="row">
          <UnitField
            label="유효율 분자"
            inputMode="numeric"
            monospace
            value={station.efficiencyNumerator}
            onChange={(v) => onPatch({ efficiencyNumerator: v })}
            {...ev('efficiency')}
          />
          <UnitField
            label="유효율 분모"
            inputMode="numeric"
            monospace
            value={station.efficiencyDenominator}
            onChange={(v) => onPatch({ efficiencyDenominator: v })}
            {...ev('efficiency')}
          />
        </div>
      </details>
    </div>
  )
}
