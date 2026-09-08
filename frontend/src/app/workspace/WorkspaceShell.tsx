import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  buildFixtureContent,
  buildRunRequest,
  createPayloadForm,
  draftFromPreset,
  emptyDraft,
  dependenciesReferencing,
  orbitFormFromSpec,
  payloadFormFromTemplate,
  referencedPayloadKeys,
  stationFormFromDto,
  type DependencyForm,
  type OrbitForm,
  type PayloadForm,
  type ScenarioDraft,
  type StationForm,
} from '../../features/scenario/draft'
import { DEFAULT_PRESET } from '../../features/scenario/presets'
import { useRunScenario, type SubmittedContext } from '../../features/scenario/useRunScenario'
import type { PayloadDTO, SatellitePresetPayload, StationDTO } from '../../shared/api/types'
import { stableStringify } from '../../shared/format/json'
import { nextEditId, uniqueStableKey } from '../../shared/ids'
import { cycleEvidence, type EvidenceControl, type EvidenceMark } from '../../shared/ui/evidence'
import { loadEvidenceMarks, saveEvidenceMarks } from '../../features/evidence/storage'
import { defaultEvidenceMarks } from '../../features/evidence/defaults'
import { ApiError, NetworkError } from '../../shared/api/client'
import { ScenarioSettingsForm } from '../../features/scenario/ScenarioSettingsForm'
import { SatellitePanel } from '../../features/scenario/SatellitePanel'
import { SatelliteLibrary } from '../../features/satellite/SatelliteLibrary'
import { GroundStationList, GroundStationEditor } from '../../features/scenario/GroundStationList'
import { StationLibrary } from '../../features/station/StationLibrary'
import { PayloadImportPanel, type PayloadDraftInput } from '../../features/payload/PayloadImportPanel'
import { PayloadCatalog } from '../../features/payload/PayloadCatalog'
import { PayloadCart, PayloadDetail } from '../../features/payload/PayloadCart'
import { DependencyPanel } from '../../features/payload/DependencyPanel'
import { ScenarioLibrary } from '../../features/library/ScenarioLibrary'
import { ScenarioComparePanel } from '../../features/comparison/ScenarioComparePanel'
import { ReportExportPanel } from '../../features/report/ReportExportPanel'

import { TopBar } from './TopBar'
import { ContextSidebar } from './ContextSidebar'
import { GlobeStage } from './GlobeStage'
import { WorkspaceToolbar } from './WorkspaceToolbar'
import { BottomDock } from './BottomDock'
import { HelpPanel } from './HelpPanel'
import { ResultTables, type DockTab } from './ResultTables'
import { FloatingPanel } from './FloatingPanel'
import { CompanionDetailPanel } from './CompanionDetailPanel'
import { usePanels, type PanelId, type PanelPosition } from './usePanels'

const DEFAULT_DOCK_POS: PanelPosition = { x: 24, y: 96 }

function requestIdentity(request: ReturnType<typeof buildRunRequest>): string {
  return 'fixture' in request ? `fixture:${request.fixture}` : `snapshot:${stableStringify(request.snapshot)}`
}

/** A stable signature of everything a save would persist (friendly name + executable content), used
 *  to tell "저장되지 않은 변경" apart from "재계산 필요". Null when the draft can't currently build. */
function contentSignature(draft: ScenarioDraft): string | null {
  try {
    return stableStringify({ name: draft.scenarioName, content: buildFixtureContent(draft) })
  } catch {
    return null
  }
}

function contextFromDraft(draft: ScenarioDraft): SubmittedContext {
  return {
    analysisMode: draft.analysisMode,
    windowStart: draft.analysisWindowStart,
    windowEnd: draft.analysisWindowEnd,
    activeStationKeys: draft.stations.filter((s) => s.active).map((s) => s.stableKey),
    content: buildFixtureContent(draft),
  }
}

/** Small screens (or short heights) switch floating panels to drawers and stack the sidebar. */
function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(max-width: 860px)').matches,
  )
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 860px)')
    const on = () => setNarrow(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return narrow
}

const PANEL_TITLE: Record<PanelId, string> = {
  settings: '설정',
  cart: '모델 출력 장바구니',
  library: '시나리오 저장/불러오기',
  compare: '실행 비교',
  report: '보고서',
  help: '도움말',
}

/**
 * The globe-centred single workspace. All scenario input and run state live here (reused verbatim
 * from the previous long-scroll layout); only the *arrangement* changed — a thin top bar, a context
 * rail, a full-bleed globe stage, floating tool panels, and a collapsible result dock. Panel/dock/map
 * visibility are screen state and never enter the run or its hash.
 */
export function WorkspaceShell() {
  const [draft, setDraft] = useState<ScenarioDraft>(() => draftFromPreset(DEFAULT_PRESET))
  const [selectedPassKey, setSelectedPassKey] = useState<string | null>(null)
  const [hiddenStationKeys, setHiddenStationKeys] = useState<ReadonlySet<string>>(() => new Set())
  const [dockMode, setDockMode] = useState<'closed' | 'docked' | 'floating'>('closed')
  const [dockPos, setDockPos] = useState<PanelPosition>(DEFAULT_DOCK_POS)
  const [dockZ, setDockZ] = useState(60)
  const [dockTab, setDockTab] = useState<DockTab>('pass')
  const [settingsTab, setSettingsTab] = useState<'orbit' | 'stations' | 'basics'>('basics')
  const [selectedStationEditId, setSelectedStationEditId] = useState<string | null>(null)
  const [selectedPayloadEditId, setSelectedPayloadEditId] = useState<string | null>(null)
  const [libraryMode, setLibraryMode] = useState<'open' | 'save'>('open')
  // Saved-item libraries open as companion windows attached to the settings panel (they close with it).
  const [satLibOpen, setSatLibOpen] = useState(false)
  const [stationLibOpen, setStationLibOpen] = useState(false)
  const [chaseCam, setChaseCam] = useState(false)
  const [resetViewNonce, setResetViewNonce] = useState(0)
  const [payloadAddOpen, setPayloadAddOpen] = useState(false)
  const [savedSig, setSavedSig] = useState<string | null>(() =>
    contentSignature(draftFromPreset(DEFAULT_PRESET)),
  )
  const { phase, lastRun, history, error, run, reset } = useRunScenario()
  const panels = usePanels()
  const narrow = useNarrow()

  // Per-field evidence marks (measured / provisional / assumption). Display-only bookkeeping kept
  // OUT of the draft so it never enters the executable content, hash, or "unsaved" detection. Marks
  // are keyed per scenario and persisted in localStorage, so reopening a scenario restores them.
  const scenarioKey = draft.savedScenarioId ?? draft.presetFixtureId
  const scenarioKeyRef = useRef(scenarioKey)
  // Effective marks = the scenario's seeded defaults (how much is assumption/estimate/measured) with
  // the user's stored changes layered on top (their edits win).
  const marksFor = (key: string) => ({ ...defaultEvidenceMarks(key), ...loadEvidenceMarks(key) })
  const [evidenceMarks, setEvidenceMarks] = useState<Record<string, EvidenceMark>>(() =>
    marksFor(scenarioKey),
  )
  useEffect(() => {
    // On a scenario switch (new / open / preset), swap in that scenario's marks (defaults + saved).
    if (scenarioKeyRef.current !== scenarioKey) {
      scenarioKeyRef.current = scenarioKey
      setEvidenceMarks(marksFor(scenarioKey))
    }
  }, [scenarioKey])
  const cycleFieldEvidence = useCallback((fieldKey: string) => {
    setEvidenceMarks((prev) => {
      const next = { ...prev, [fieldKey]: cycleEvidence(prev[fieldKey] ?? 'unset') }
      saveEvidenceMarks(scenarioKeyRef.current, next)
      return next
    })
  }, [])
  const evidenceControl = useMemo<EvidenceControl>(
    () => ({ get: (k) => evidenceMarks[k] ?? 'unset', cycle: cycleFieldEvidence }),
    [evidenceMarks, cycleFieldEvidence],
  )

  // Load/replace the whole draft. `switch` marks a real scenario change (new/preset/open) so the
  // previous run is cleared — different scenarios must never share the same globe/budget/progress
  // (spec §4). A save-rebase passes no `switch`, so the current result is kept.
  const loadDraft = useCallback(
    (next: ScenarioDraft, opts?: { switch?: boolean }) => {
      setDraft(next)
      setSelectedPassKey(null)
      setSavedSig(contentSignature(next))
      if (opts?.switch) {
        reset()
      }
    },
    [reset],
  )

  // Guard a scenario switch so unsaved edits are not lost silently. Reads unsaved via a ref so the
  // confirm reflects the latest state without recreating every switch handler each render. Cancelling
  // keeps the current draft and run untouched (spec §4).
  const unsavedRef = useRef(false)
  const guardSwitch = useCallback((fn: () => void) => {
    if (
      unsavedRef.current &&
      !window.confirm('저장되지 않은 변경이 있습니다. 계속하면 현재 편집 내용이 사라질 수 있습니다. 계속할까요?')
    ) {
      return
    }
    fn()
  }, [])

  // ---- immutable patch helpers (unchanged from the previous workspace) ------------------------
  const patch = useCallback((partial: Partial<ScenarioDraft>) => setDraft((d) => ({ ...d, ...partial })), [])
  const patchOrbit = useCallback(
    (partial: Partial<OrbitForm>) => setDraft((d) => ({ ...d, orbit: { ...d.orbit, ...partial } })),
    [],
  )
  const patchStation = useCallback((editId: string, partial: Partial<StationForm>) => {
    setDraft((d) => ({
      ...d,
      stations: d.stations.map((s) => (s.editId === editId ? { ...s, ...partial } : s)),
    }))
  }, [])
  const removeStation = useCallback((editId: string) => {
    setDraft((d) => ({ ...d, stations: d.stations.filter((s) => s.editId !== editId) }))
  }, [])
  // Add a station (from the library: 예시/저장된/새 등록) INTO the current scenario. A colliding stable
  // key is re-keyed so both stay addressable; the source station DTO is never mutated.
  const addStationFromDto = useCallback((station: StationDTO) => {
    setDraft((d) => {
      const existing = new Set(d.stations.map((s) => s.stableKey))
      const key = existing.has(station.stable_key) ? uniqueStableKey(existing) : station.stable_key
      const form = stationFormFromDto({ ...structuredClone(station), stable_key: key })
      return { ...d, stations: [...d.stations, { ...form, active: true }] }
    })
  }, [])
  // Apply a saved SATELLITE into THIS scenario only: replace the orbit + name; stations, output cart
  // and analysis window are kept. The orbit change marks 재계산 필요.
  const onApplySatellitePreset = useCallback((payload: SatellitePresetPayload) => {
    setDraft((d) => ({
      ...d,
      satelliteName: payload.name,
      satelliteProvenance: payload.provenance,
      satelliteIsAssumption: payload.isAssumption,
      orbit: orbitFormFromSpec(payload.orbit, d.analysisWindowStart),
    }))
  }, [])

  const patchPayload = useCallback((editId: string, partial: Partial<PayloadForm>) => {
    setDraft((d) => {
      const referenced = referencedPayloadKeys(d.dependencies)
      return {
        ...d,
        payloads: d.payloads.map((p) => {
          if (p.editId !== editId) return p
          if (partial.stableKey !== undefined && partial.stableKey !== p.stableKey && referenced.has(p.stableKey)) {
            return p
          }
          return { ...p, ...partial }
        }),
      }
    })
  }, [])
  const removePayload = useCallback((editId: string) => {
    setDraft((d) => {
      const target = d.payloads.find((p) => p.editId === editId)
      if (target && referencedPayloadKeys(d.dependencies).has(target.stableKey)) return d
      return { ...d, payloads: d.payloads.filter((p) => p.editId !== editId) }
    })
  }, [])
  const addDependency = useCallback((predecessorKey: string, successorKey: string) => {
    setDraft((d) => ({
      ...d,
      dependencies: [
        ...d.dependencies,
        { editId: nextEditId('dep'), predecessorKey, successorKey, kind: 'SEND_AFTER' },
      ],
    }))
  }, [])
  const removeDependency = useCallback((editId: string) => {
    setDraft((d) => ({ ...d, dependencies: d.dependencies.filter((x) => x.editId !== editId) }))
  }, [])
  const addPayloadFromInput = useCallback((input: PayloadDraftInput) => {
    setDraft((d) => {
      const existing = new Set(d.payloads.map((p) => p.stableKey))
      const key = uniqueStableKey(existing, 'OUTPUT')
      const maxSeq = d.payloads.reduce((mx, p) => Math.max(mx, Number(p.queueSequence) || 0), 0)
      const form = createPayloadForm({
        stableKey: key,
        displayName: input.displayName,
        logicalSizeBytes: input.logicalSizeBytes,
        readyAt: d.analysisWindowStart,
        queueSequence: maxSeq + 1,
        sizeSource: input.sizeSource,
      })
      return { ...d, payloads: [...d.payloads, form] }
    })
  }, [])
  const addTemplatePayload = useCallback((template: PayloadDTO) => {
    setDraft((d) => {
      if (d.payloads.some((p) => p.stableKey === template.stable_key)) return d
      return { ...d, payloads: [...d.payloads, payloadFormFromTemplate(template)] }
    })
  }, [])

  const toggleHidden = useCallback((stationKey: string) => {
    setHiddenStationKeys((prev) => {
      const next = new Set(prev)
      if (next.has(stationKey)) next.delete(stationKey)
      else next.add(stationKey)
      return next
    })
  }, [])

  // ---- request build + run --------------------------------------------------------------------
  type Built =
    | { request: ReturnType<typeof buildRunRequest>; identity: string }
    | { buildError: string }
  const built = useMemo<Built>(() => {
    try {
      const request = buildRunRequest(draft)
      return { request, identity: requestIdentity(request) }
    } catch (err) {
      return { buildError: (err as Error).message }
    }
  }, [draft])
  const buildError = 'buildError' in built ? built.buildError : null
  const currentIdentity = 'identity' in built ? built.identity : null
  const isStale = lastRun !== null && currentIdentity !== lastRun.inputIdentity

  // "저장되지 않은 변경" (unsaved edits vs the last saved/loaded baseline) is a SEPARATE axis from
  // "재계산 필요" (isStale, edits since the last run). A save clears unsaved; a run clears stale.
  const currentSig = useMemo(() => contentSignature(draft), [draft])
  const unsaved = savedSig !== null && currentSig !== savedSig
  useEffect(() => {
    unsavedRef.current = unsaved
  }, [unsaved])

  const onNewScenario = useCallback(
    () => guardSwitch(() => loadDraft(emptyDraft(), { switch: true })),
    [guardSwitch, loadDraft],
  )
  const onRenameScenario = useCallback((name: string) => setDraft((d) => ({ ...d, scenarioName: name })), [])
  const onOpenLibrary = useCallback(
    (mode: 'open' | 'save') => {
      setLibraryMode(mode)
      panels.open('library')
    },
    [panels],
  )

  // Sidebar → settings-panel entry points (the sidebar lists open the existing floating panels).
  const openSatelliteSettings = useCallback(() => {
    setSettingsTab('orbit')
    panels.open('settings')
  }, [panels])
  const openStationSettings = useCallback(
    (editId: string) => {
      setSelectedStationEditId(editId)
      setStationLibOpen(false)
      setSettingsTab('stations')
      panels.open('settings')
    },
    [panels],
  )
  const openStationAdd = useCallback(() => {
    setSettingsTab('stations')
    panels.open('settings')
  }, [panels])
  const openHelp = useCallback(() => panels.open('help'), [panels])

  // Sidebar model-output list → the cart floating panel (open the specific output, or the add menu).
  const openPayloadSettings = useCallback(
    (editId: string) => {
      setSelectedPayloadEditId(editId)
      setPayloadAddOpen(false)
      panels.open('cart')
    },
    [panels],
  )
  const openPayloadAdd = useCallback(() => {
    setSelectedPayloadEditId(null)
    setPayloadAddOpen(true)
    panels.open('cart')
  }, [panels])

  const onRun = useCallback(() => {
    if (!('request' in built)) return
    run(built.request, built.identity, contextFromDraft(draft))
  }, [built, run, draft])

  const floatDock = useCallback((pos: PanelPosition) => {
    setDockPos(pos)
    setDockMode('floating')
    setDockZ((z) => z + 1)
  }, [])

  const onResetView = useCallback(() => {
    panels.resetAll()
    setHiddenStationKeys(new Set())
    setDockMode('closed')
    setDockPos(DEFAULT_DOCK_POS)
    setChaseCam(false)
    setResetViewNonce((n) => n + 1) // return the globe camera to the run's first composition
  }, [panels])

  const panelFor = (id: PanelId, body: React.ReactNode) => (
    <FloatingPanel
      key={id}
      title={PANEL_TITLE[id]}
      open={panels.isOpen(id)}
      pos={panels.panels[id].pos}
      z={panels.panels[id].z}
      asDrawer={narrow}
      onClose={() => panels.close(id)}
      onFocus={() => panels.focus(id)}
      onMove={(pos) => panels.move(id, pos)}
      onResetPosition={() => panels.resetPosition(id)}
    >
      {body}
    </FloatingPanel>
  )

  return (
    <div className="workspace-shell">
      <TopBar
        draft={draft}
        phase={phase}
        lastRun={lastRun}
        isStale={isStale}
        unsaved={unsaved}
        buildError={buildError}
        onRun={onRun}
        onNewScenario={onNewScenario}
        onRenameScenario={onRenameScenario}
        onOpenLibrary={onOpenLibrary}
      />

      <div className={narrow ? 'workspace-shell__body workspace-shell__body--narrow' : 'workspace-shell__body'}>
        <ContextSidebar
          draft={draft}
          lastRun={lastRun}
          isStale={isStale}
          hasError={!!error}
          hiddenStationKeys={hiddenStationKeys}
          onToggleHidden={toggleHidden}
          patchStation={patchStation}
          onOpenSatellite={openSatelliteSettings}
          onOpenStation={openStationSettings}
          onAddStation={openStationAdd}
          onOpenPayload={openPayloadSettings}
          onAddPayload={openPayloadAdd}
          onOpenHelp={openHelp}
        />

        <div className="workspace-shell__stage">
          <GlobeStage
            lastRun={lastRun}
            draft={draft}
            hiddenStationKeys={hiddenStationKeys}
            selectedPassKey={selectedPassKey}
            onSelectPass={setSelectedPassKey}
            chaseCam={chaseCam}
            resetViewNonce={resetViewNonce}
          />

          <WorkspaceToolbar
            isOpen={panels.isOpen}
            onToggle={panels.toggle}
            onResetView={onResetView}
            chaseCam={chaseCam}
            onToggleChase={() => setChaseCam((v) => !v)}
          />

          {error ? (
            <div className="stage-toast" role="alert">
              <strong>실행 실패</strong> — {describeError(error)}
              {lastRun ? ' 아래·좌측은 직전 성공 실행 기준입니다.' : ''}
            </div>
          ) : null}
          {buildError ? (
            <div className="stage-toast stage-toast--warn" role="status">
              입력을 실행 가능한 형식으로 변환할 수 없습니다: {buildError}
            </div>
          ) : null}

          {dockMode !== 'floating' ? (
            <BottomDock
              mode={dockMode === 'docked' ? 'docked' : 'closed'}
              lastRun={lastRun}
              selectedPassKey={selectedPassKey}
              onSelectPass={setSelectedPassKey}
              tab={dockTab}
              onTabChange={setDockTab}
              onOpen={() => setDockMode('docked')}
              onClose={() => setDockMode('closed')}
              onFloat={floatDock}
            />
          ) : null}
        </div>
      </div>

      {panelFor(
        'settings',
        <div className="settings-panel">
          <div className="settings-panel__tabs" role="tablist">
            <button type="button" role="tab" aria-selected={settingsTab === 'basics'} className={settingsTab === 'basics' ? 'settings-panel__tab settings-panel__tab--active' : 'settings-panel__tab'} onClick={() => setSettingsTab('basics')}>기본·분석</button>
            <button type="button" role="tab" aria-selected={settingsTab === 'orbit'} className={settingsTab === 'orbit' ? 'settings-panel__tab settings-panel__tab--active' : 'settings-panel__tab'} onClick={() => setSettingsTab('orbit')}>위성</button>
            <button type="button" role="tab" aria-selected={settingsTab === 'stations'} className={settingsTab === 'stations' ? 'settings-panel__tab settings-panel__tab--active' : 'settings-panel__tab'} onClick={() => setSettingsTab('stations')}>지상국</button>
          </div>
          {settingsTab === 'basics' ? (
            <>
              <ScenarioSettingsForm draft={draft} patch={patch} />
              <StrategyField draft={draft} patch={patch} inFlight={phase === 'submitting' || phase === 'loading-results'} />
            </>
          ) : settingsTab === 'orbit' ? (
            <SatellitePanel
              draft={draft}
              patch={patch}
              patchOrbit={patchOrbit}
              onOpenLibrary={() => setSatLibOpen(true)}
              evidence={evidenceControl}
            />
          ) : (
            <GroundStationList
              stations={draft.stations}
              patchStation={patchStation}
              removeStation={removeStation}
              hiddenStationKeys={hiddenStationKeys}
              onToggleHidden={toggleHidden}
              onOpenLibrary={() => {
                setSelectedStationEditId(null)
                setStationLibOpen(true)
              }}
              selectedEditId={selectedStationEditId}
              onSelectEditId={(id) => {
                setSelectedStationEditId(id)
                if (id) setStationLibOpen(false)
              }}
            />
          )}
        </div>,
      )}
      {panelFor(
        'cart',
        <>
          <PayloadCart
            payloads={draft.payloads}
            patchPayload={patchPayload}
            removePayload={removePayload}
            analysisMode={draft.analysisMode}
            referencedKeys={referencedPayloadKeys(draft.dependencies)}
            referencingText={(key) =>
              dependenciesReferencing(draft.dependencies, key)
                .map((dep: DependencyForm) => `${dep.predecessorKey} → ${dep.successorKey}`)
                .join(', ')
            }
            selectedEditId={selectedPayloadEditId}
            onSelectEditId={(id) => {
              setSelectedPayloadEditId(id)
              if (id) setPayloadAddOpen(false)
            }}
          />
          <button
            type="button"
            className="btn btn--primary library-panel__add"
            onClick={() => {
              setSelectedPayloadEditId(null)
              setPayloadAddOpen(true)
            }}
          >
            ＋ 출력 추가
          </button>
          <details className="card cart-collapsible">
            <summary>고급 편집 — 출력 의존성</summary>
            <DependencyPanel
              dependencies={draft.dependencies}
              payloads={draft.payloads}
              onAdd={addDependency}
              onRemove={removeDependency}
            />
          </details>
        </>,
      )}
      {panelFor('library', <ScenarioLibrary draft={draft} unsaved={unsaved} onLoadDraft={loadDraft} mode={libraryMode} />)}
      {panelFor('compare', <ScenarioComparePanel history={history} />)}
      {panelFor('report', <ReportExportPanel history={history} />)}
      {panelFor('help', <HelpPanel />)}

      {/* Detail windows attached to the RIGHT of their list panels (settings→station, cart→output),
          following the parent, closing with it, and swapping content when another item is selected. */}
      {/* Saved-item libraries: companion windows attached to the settings panel; rendered only while
          settings is open and the matching tab is active, so closing settings closes them too. */}
      {panels.isOpen('settings') && settingsTab === 'orbit' && satLibOpen ? (
        <CompanionDetailPanel
          title="위성 저장·불러오기"
          anchorPos={panels.panels.settings.pos}
          anchorWidth={380}
          z={panels.panels.settings.z + 1}
          asDrawer={narrow}
          onClose={() => setSatLibOpen(false)}
        >
          <SatelliteLibrary onApply={onApplySatellitePreset} />
        </CompanionDetailPanel>
      ) : null}
      {panels.isOpen('settings') && settingsTab === 'stations' && stationLibOpen ? (
        <CompanionDetailPanel
          title="지상국 저장·불러오기"
          anchorPos={panels.panels.settings.pos}
          anchorWidth={380}
          z={panels.panels.settings.z + 2}
          asDrawer={narrow}
          onClose={() => setStationLibOpen(false)}
        >
          <StationLibrary onAddStation={addStationFromDto} />
        </CompanionDetailPanel>
      ) : null}
      {(() => {
        const station =
          panels.isOpen('settings') && settingsTab === 'stations'
            ? draft.stations.find((s) => s.editId === selectedStationEditId) ?? null
            : null
        return station ? (
          <CompanionDetailPanel
            title={`지상국 상세 — ${station.stableKey}`}
            anchorPos={panels.panels.settings.pos}
            anchorWidth={380}
            z={panels.panels.settings.z + 1}
            asDrawer={narrow}
            onClose={() => setSelectedStationEditId(null)}
          >
            <GroundStationEditor
              station={station}
              onPatch={(p) => patchStation(station.editId, p)}
              evidence={evidenceControl}
            />
          </CompanionDetailPanel>
        ) : null
      })()}
      {panels.isOpen('cart') && payloadAddOpen ? (
        <CompanionDetailPanel
          title="출력 추가"
          anchorPos={panels.panels.cart.pos}
          anchorWidth={380}
          z={panels.panels.cart.z + 2}
          asDrawer={narrow}
          onClose={() => setPayloadAddOpen(false)}
        >
          <PayloadImportPanel onAdd={addPayloadFromInput} />
          <PayloadCatalog
            templates={(draft.baseContent.payloads ?? []) as PayloadDTO[]}
            currentKeys={new Set(draft.payloads.map((p) => p.stableKey))}
            onAdd={addTemplatePayload}
          />
        </CompanionDetailPanel>
      ) : null}
      {(() => {
        const payload = panels.isOpen('cart') && !payloadAddOpen
          ? draft.payloads.find((p) => p.editId === selectedPayloadEditId) ?? null
          : null
        return payload ? (
          <CompanionDetailPanel
            title="출력 상세"
            anchorPos={panels.panels.cart.pos}
            anchorWidth={380}
            z={panels.panels.cart.z + 1}
            asDrawer={narrow}
            onClose={() => setSelectedPayloadEditId(null)}
          >
            <PayloadDetail
              payload={payload}
              onPatch={(p) => patchPayload(payload.editId, p)}
              excluded={draft.analysisMode === 'NETWORK_ONLY'}
              referenced={referencedPayloadKeys(draft.dependencies).has(payload.stableKey)}
              referencingText={dependenciesReferencing(draft.dependencies, payload.stableKey)
                .map((dep: DependencyForm) => `${dep.predecessorKey} → ${dep.successorKey}`)
                .join(', ')}
            />
          </CompanionDetailPanel>
        ) : null
      })()}

      {dockMode === 'floating' ? (
        <FloatingPanel
          title="결과 표"
          open
          pos={dockPos}
          z={dockZ}
          asDrawer={narrow}
          width={560}
          className="fpanel--results"
          onClose={() => setDockMode('closed')}
          onFocus={() => setDockZ((z) => z + 1)}
          onMove={setDockPos}
          onResetPosition={() => setDockPos(DEFAULT_DOCK_POS)}
          extraActions={
            <button
              type="button"
              className="fpanel__btn"
              onClick={() => setDockMode('docked')}
              title="다시 도킹"
            >
              ⊟
              <span className="sr-only">다시 도킹</span>
            </button>
          }
        >
          <ResultTables
            lastRun={lastRun}
            selectedPassKey={selectedPassKey}
            onSelectPass={setSelectedPassKey}
            tab={dockTab}
            onTabChange={setDockTab}
          />
        </FloatingPanel>
      ) : null}
    </div>
  )
}

/** Execution-strategy selector (kept out of the top bar). NETWORK_ONLY is exact-only, shown and
 *  disabled so the displayed value equals what is sent. */
function StrategyField({
  draft,
  patch,
  inFlight,
}: {
  draft: ScenarioDraft
  patch: (partial: Partial<ScenarioDraft>) => void
  inFlight: boolean
}) {
  const networkOnly = draft.analysisMode === 'NETWORK_ONLY'
  const shown = networkOnly ? 'EXACT_GLOBAL' : draft.executionStrategy
  return (
    <div className="unit-field">
      <label htmlFor="exec-strategy">실행 전략</label>
      <select
        id="exec-strategy"
        value={shown}
        disabled={inFlight || networkOnly}
        onChange={(e) => patch({ executionStrategy: e.target.value as ScenarioDraft['executionStrategy'] })}
      >
        <option value="EXACT_GLOBAL">EXACT_GLOBAL (정확·전역 최적)</option>
        <option value="BOUNDED_APPROXIMATE">BOUNDED_APPROXIMATE (근사)</option>
      </select>
      {networkOnly ? (
        <p className="unit-field__help">NETWORK_ONLY는 정확 해가 있어 EXACT_GLOBAL만 사용합니다.</p>
      ) : null}
    </div>
  )
}

function describeError(error: ApiError | NetworkError | Error): string {
  if (error instanceof ApiError) {
    const fields = error.fieldPaths.length ? ` (필드: ${error.fieldPaths.join(', ')})` : ''
    return `[${error.code}] ${error.message}${fields}`
  }
  if (error instanceof NetworkError) {
    return error.possiblyDelivered
      ? `${error.message} 요청이 서버에 도달했을 수 있으므로 자동 재시도하지 않습니다.`
      : error.message
  }
  return error.message
}
