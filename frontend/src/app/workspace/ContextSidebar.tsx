import type { ScenarioDraft, StationForm } from '../../features/scenario/draft'
import type { SubmittedRun } from '../../features/scenario/useRunScenario'
import type { RunResult } from '../../shared/api/types'
import { formatBytesAdaptive, bytesToExactBytes, bytesStringToAdaptiveHint } from '../../shared/format/units'
import { formatUtc } from '../../shared/format/time'
import { analysisModeLabel, serviceClassLabel } from '../../shared/format/labels'
import { udegToDeg } from '../../shared/format/friendly'

export interface ContextSidebarProps {
  draft: ScenarioDraft
  lastRun: SubmittedRun | null
  isStale: boolean
  /** The most recent run attempt failed — the shown result (if any) is the previous success. */
  hasError: boolean
  hiddenStationKeys: ReadonlySet<string>
  onToggleHidden: (stableKey: string) => void
  /** Toggle a station's "계산 포함" (a real input → triggers 재계산 필요). */
  patchStation: (editId: string, partial: Partial<StationForm>) => void
  /** Open the settings panel focused on the satellite (edit / replace-from-preset). */
  onOpenSatellite: () => void
  /** Open the settings panel focused on a specific ground station's detail. */
  onOpenStation: (editId: string) => void
  /** Open the settings panel's station tab to add (new / from preset). */
  onAddStation: () => void
  /** Open the cart panel focused on a specific model output's detail. */
  onOpenPayload: (editId: string) => void
  /** Open the cart panel (add: paste / file / assumed size / template). */
  onAddPayload: () => void
  /** Open in-app help (assumptions, terms, general limits). */
  onOpenHelp: () => void
}

/**
 * The left rail, reorganised to just three sections (transfer budget, satellite, ground stations).
 * The budget number reads first; the satellite and stations are tidy file-explorer-style lists whose
 * rows open the existing floating settings panels rather than expanding forms inline. Per-station map
 * visibility (👁) stays screen-only and distinct from "계산 포함" (a real input). Long assumptions and
 * the per-pass detail moved to Help / the result tables; only short result states remain here.
 */
export function ContextSidebar(props: ContextSidebarProps) {
  const {
    draft,
    lastRun,
    isStale,
    hasError,
    hiddenStationKeys,
    onToggleHidden,
    patchStation,
    onOpenSatellite,
    onOpenStation,
    onAddStation,
    onOpenPayload,
    onAddPayload,
    onOpenHelp,
  } = props
  const result = lastRun?.envelope.result ?? null
  const networkOnly = draft.analysisMode === 'NETWORK_ONLY'

  const inc = /^-?\d+$/.test(draft.orbit.inclinationUdeg.trim())
    ? `${udegToDeg(Number(draft.orbit.inclinationUdeg))}°`
    : '—'
  const orbitSummary = `${draft.orbit.mode === 'GP_TLE' ? 'TLE' : '2체 요소'} · 경사각 ${inc}`

  return (
    <aside className="sidebar" aria-label="시나리오 컨텍스트">
      {/* ── 1. 전송 예산 ──────────────────────────────────────────── */}
      <section className="sidebar__block sidebar__block--budget">
        <div className="sidebar__head">
          <h2 className="sidebar__title">전송 예산</h2>
          <button type="button" className="sidebar__icon-btn" onClick={onOpenHelp} title="도움말 · 용어 · 가정과 한계" aria-label="도움말 열기">
            ⓘ
          </button>
        </div>
        {result && lastRun ? (
          <BudgetHero result={result} stale={isStale} hasError={hasError} context={lastRun.context} />
        ) : (
          <p className="sidebar__empty">
            아직 계산 전입니다. 상단 “재계산”을 누르면 전송 예산이 계산됩니다.
          </p>
        )}
      </section>

      {/* ── 2. 위성 ──────────────────────────────────────────────── */}
      <section className="sidebar__block">
        <div className="sidebar__head">
          <h2 className="sidebar__title">위성</h2>
          <button
            type="button"
            className="sidebar__icon-btn"
            onClick={onOpenSatellite}
            title="위성 설정 (편집 또는 프리셋 궤도로 교체) — 단일 위성 모델"
            aria-label="위성 설정 열기"
          >
            ⚙
          </button>
        </div>
        <ul className="filelist">
          <li className="filerow">
            <button type="button" className="filerow__name" onClick={onOpenSatellite} title="위성 설정 열기">
              <span className="filerow__title">{draft.satelliteName || '위성'}</span>
              <span className="filerow__sub">{orbitSummary}</span>
            </button>
          </li>
        </ul>
      </section>

      {/* ── 3. 지상국 ────────────────────────────────────────────── */}
      <section className="sidebar__block">
        <div className="sidebar__head">
          <h2 className="sidebar__title">
            지상국 <span className="sidebar__count">{draft.stations.length}</span>
          </h2>
          <button
            type="button"
            className="sidebar__icon-btn"
            onClick={onAddStation}
            title="지상국 추가 (새로 만들기 · 프리셋에서 가져오기)"
            aria-label="지상국 추가"
          >
            ＋
          </button>
        </div>
        <ul className="filelist">
          {draft.stations.map((s) => {
            const shownOnMap = !hiddenStationKeys.has(s.stableKey)
            return (
              <li key={s.editId} className={s.active ? 'filerow' : 'filerow filerow--inactive'}>
                <label className="filerow__check" title="계산에 포함 — 변경하면 재계산이 필요합니다">
                  <input
                    type="checkbox"
                    checked={s.active}
                    onChange={(e) => patchStation(s.editId, { active: e.target.checked })}
                  />
                  <span className="sr-only">계산에 포함</span>
                </label>
                <button
                  type="button"
                  className="filerow__name"
                  onClick={() => onOpenStation(s.editId)}
                  title="지상국 설정 열기"
                >
                  <span className="filerow__title mono">{s.stableKey}</span>
                  <span className="filerow__sub">{s.active ? '계산 포함' : '계산 제외'}</span>
                </button>
                <button
                  type="button"
                  className={shownOnMap ? 'filerow__eye' : 'filerow__eye filerow__eye--off'}
                  onClick={() => onToggleHidden(s.stableKey)}
                  aria-pressed={shownOnMap}
                  title={shownOnMap ? '지도에서 숨기기 (표시만, 계산 불변)' : '지도에 표시 (표시만, 계산 불변)'}
                >
                  {shownOnMap ? '👁' : '🚫'}
                  <span className="sr-only">지도 표시 전환</span>
                </button>
              </li>
            )
          })}
        </ul>
      </section>

      {/* ── 4. 모델 출력 ─────────────────────────────────────────── */}
      <section className="sidebar__block">
        <div className="sidebar__head">
          <h2 className="sidebar__title">
            모델 출력 <span className="sidebar__count">{draft.payloads.length}</span>
          </h2>
          <button
            type="button"
            className="sidebar__icon-btn"
            onClick={onAddPayload}
            title="출력 추가 (붙여넣기 · 파일 · 가정 크기 · 템플릿)"
            aria-label="모델 출력 추가"
          >
            ＋
          </button>
        </div>
        {networkOnly ? (
          <p className="sidebar__hint">전송 예산만 실행에서는 출력이 제외됩니다(초안은 보존).</p>
        ) : null}
        {draft.payloads.length === 0 ? (
          <p className="sidebar__empty">출력이 없습니다. ‘＋’로 추가하세요.</p>
        ) : (
          <ul className="filelist">
            {draft.payloads.map((p) => {
              const size = bytesStringToAdaptiveHint(p.logicalSizeBytes) ?? `${p.logicalSizeBytes} B`
              return (
                <li key={p.editId} className={networkOnly ? 'filerow filerow--inactive' : 'filerow'}>
                  <span className="filerow__emoji" aria-hidden="true">{p.emoji}</span>
                  <button
                    type="button"
                    className="filerow__name"
                    onClick={() => onOpenPayload(p.editId)}
                    title="출력 설정 열기"
                  >
                    <span className="filerow__title">{p.displayName || p.stableKey}</span>
                    <span className="filerow__sub">{size} · {serviceClassLabel(p.serviceClass)}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <p className="sidebar__disclaimer">
        결과는 <strong>모델 추정(가정 입력)</strong>이며 실제 지상 수신·운용 승인·비행 성능 인증이 아닙니다.
      </p>
    </aside>
  )
}

function BudgetHero({
  result,
  stale,
  hasError,
  context,
}: {
  result: RunResult
  stale: boolean
  hasError: boolean
  context: SubmittedRun['context']
}) {
  const m = result.metrics
  const computed = result.calculation_status === 'COMPUTED'
  const optimal = result.optimization.optimization_status === 'EXACT' && result.optimization.globally_optimal
  const queueAware = m.payload_allocated_bytes != null
  const budget = m.scheduled_unique_capacity_bytes
  const allocated = m.payload_allocated_bytes ?? 0
  const allocFraction = queueAware && budget > 0 ? Math.min(1, Math.max(0, allocated / budget)) : 0

  return (
    <>
      <div className="budget-hero">
        <span className="budget-hero__value" title={bytesToExactBytes(budget)}>
          {formatBytesAdaptive(budget)}
        </span>
      </div>
      <div className="budget-hero__basis" title={`${context.windowStart} → ${context.windowEnd}`}>
        <span className="mono">{formatUtc(context.windowStart)}</span>
        <span className="mono">→ {formatUtc(context.windowEnd)}</span>
        <span className="mono" title={analysisModeLabel(context.analysisMode)}>{context.analysisMode}</span>
      </div>

      {queueAware ? (
        <div className="budget-alloc">
          <div className="budget-alloc__bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(allocFraction * 100)}>
            <div className="budget-alloc__fill" style={{ width: `${Math.round(allocFraction * 100)}%` }} />
          </div>
          <dl className="budget-alloc__facts">
            <div>
              <dt>할당된 출력</dt>
              <dd title={bytesToExactBytes(allocated)}>{formatBytesAdaptive(allocated)}</dd>
            </div>
            <div>
              <dt>미전송 출력</dt>
              <dd title={m.payload_remaining_bytes == null ? undefined : bytesToExactBytes(m.payload_remaining_bytes)}>
                {m.payload_remaining_bytes == null ? '해당 없음' : formatBytesAdaptive(m.payload_remaining_bytes)}
              </dd>
            </div>
          </dl>
        </div>
      ) : (
        <p className="sidebar__hint">전송 예산만(출력 배분 없음) — 할당·미전송은 해당 없음.</p>
      )}

      <div className="sidebar__chips">
        <span className="chip chip--assumption" title="가정 입력에 기반한 모델 추정값입니다">가정 기반</span>
        {stale ? <span className="chip chip--warn">재계산 필요</span> : null}
        {!computed ? <span className="chip chip--warn" title="COMPUTED가 아니면 확정 예산이 아닐 수 있음">상태 {result.calculation_status}</span> : null}
        {!optimal ? <span className="chip chip--warn" title="근사 결과 — 전역 최적을 보장하지 않음">전역 최적 보장 안 됨</span> : null}
        {hasError ? <span className="chip chip--warn" title="최근 실행이 실패해 직전 성공 결과를 표시 중입니다">실행 실패 · 이전 결과</span> : null}
      </div>
    </>
  )
}
