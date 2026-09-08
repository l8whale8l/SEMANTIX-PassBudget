import type { ScenarioDraft } from './draft'
import { UnitField } from '../../shared/ui/UnitField'

export interface ScenarioSettingsFormProps {
  draft: ScenarioDraft
  patch: (partial: Partial<ScenarioDraft>) => void
}

export function ScenarioSettingsForm({ draft, patch }: ScenarioSettingsFormProps) {
  return (
    <fieldset className="card">
      <legend>시나리오 기본</legend>
      <UnitField
        label="시나리오 이름"
        help="화면 표시용 이름입니다. 계산 입력(DTO)에는 포함되지 않습니다."
        value={draft.scenarioName}
        onChange={(v) => patch({ scenarioName: v })}
      />
      <div className="row">
        <UnitField
          label="분석기간 시작"
          unit="UTC"
          help="예: 2026-09-03T00:00:00Z. 프리셋의 고정 분석기간을 현재 시각으로 덮어쓰지 않습니다."
          value={draft.analysisWindowStart}
          monospace
          onChange={(v) => patch({ analysisWindowStart: v })}
        />
        <UnitField
          label="분석기간 종료"
          unit="UTC"
          help="종료 시각은 배타적입니다(기존 시간 계약 유지)."
          value={draft.analysisWindowEnd}
          monospace
          onChange={(v) => patch({ analysisWindowEnd: v })}
        />
      </div>
      <div className="row">
        <div className="unit-field">
          <label htmlFor="analysis-mode">분석 모드</label>
          <select
            id="analysis-mode"
            value={draft.analysisMode}
            onChange={(e) =>
              patch({ analysisMode: e.target.value as ScenarioDraft['analysisMode'] })
            }
          >
            <option value="QUEUE_AWARE">QUEUE_AWARE (출력 할당 포함)</option>
            <option value="NETWORK_ONLY">NETWORK_ONLY (접촉·용량만)</option>
          </select>
          {draft.analysisMode === 'NETWORK_ONLY' ? (
            <p className="unit-field__help" role="status">
              NETWORK_ONLY 실행에는 출력물·큐 정책·저장 설정이 제외됩니다. 편집한 초안 값은
              보존되며 QUEUE_AWARE로 되돌리면 그대로 복원됩니다.
            </p>
          ) : null}
        </div>
      </div>
    </fieldset>
  )
}
