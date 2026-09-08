import { useCallback, useEffect, useMemo, useState } from 'react'

import { buildFixtureContent, type ScenarioDraft } from '../../features/scenario/draft'
import type { SubmittedRun } from '../../features/scenario/useRunScenario'
import { GlobePanel } from '../../features/globe/GlobePanel'
import { buildGlobeModel, previewGlobeModel, type GlobeModel } from '../../features/globe/model'
import { DeliveryProgressPanel } from '../../features/globe/DeliveryProgressPanel'
import {
  buildFlights,
  deliveryProgressAt,
  toSegments,
  type Flight,
  type PayloadMeta,
} from '../../features/globe/delivery'
import type { PayloadDTO } from '../../shared/api/types'

export interface GlobeStageProps {
  /** The last successful run, if any — the source of the drawn orbit + contact windows. */
  lastRun: SubmittedRun | null
  /** The current draft — used only for a pre-run station preview (no computed geometry shown). */
  draft: ScenarioDraft
  /** Stations hidden on the map (screen only — they stay in the computed result). */
  hiddenStationKeys: ReadonlySet<string>
  selectedPassKey: string | null
  onSelectPass: (stableKey: string | null) => void
  /** Lock the camera to a chase view behind/above the satellite. */
  chaseCam: boolean
  /** Bump to return the camera to the run's first composition (보기 초기화). */
  resetViewNonce: number
}

/**
 * The globe is the workspace background, not a card between tables. It is always mounted. When a run
 * exists it shows that run's geometry (orbit + contacts) and stays fixed as the draft is edited (the
 * table/stale banner handle the mismatch); before the first run it shows a stations-only preview of
 * the current draft. The model is memoised so opening/closing/dragging a panel — which never changes
 * these inputs — cannot rebuild Cesium or reset the camera/clock.
 */
export function GlobeStage({
  lastRun,
  draft,
  hiddenStationKeys,
  selectedPassKey,
  onSelectPass,
  chaseCam,
  resetViewNonce,
}: GlobeStageProps) {
  const runModel = useMemo<GlobeModel | null>(() => {
    const content = lastRun?.context.content
    if (!content || content.contact_source !== 'ORBIT_DERIVED') return null
    return buildGlobeModel(
      content,
      lastRun.envelope.result,
      lastRun.context.windowStart,
      lastRun.context.windowEnd,
    )
  }, [lastRun])

  // Pre-run preview: stations from the draft only. Rebuilt when the drawn geometry (station sites)
  // could change, keyed by a stable signature so unrelated keystrokes don't rebuild the globe.
  const previewSignature = useMemo(
    () =>
      JSON.stringify(
        draft.stations.map((s) => [
          s.stableKey,
          s.latitudeUdeg,
          s.longitudeEastUdeg,
          s.ellipsoidalHeightMm,
        ]),
      ) +
      `|${draft.analysisWindowStart}|${draft.analysisWindowEnd}`,
    [draft.stations, draft.analysisWindowStart, draft.analysisWindowEnd],
  )
  const previewModel = useMemo<GlobeModel>(() => {
    try {
      const content = buildFixtureContent(draft)
      return previewGlobeModel(content, draft.analysisWindowStart, draft.analysisWindowEnd)
    } catch {
      // An unrelated draft error (e.g. an invalid payload) blocks the run anyway; show an empty
      // preview rather than crash the stage.
      return {
        stations: [],
        track: null,
        contacts: [],
        windowStartMs: Date.parse(draft.analysisWindowStart),
        windowEndMs: Date.parse(draft.analysisWindowEnd),
        missingStationKeys: [],
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewSignature])

  const baseModel = runModel ?? previewModel
  const preview = runModel === null

  // Each output's chosen emoji (UI-only) drives both the beam flights and the progress-panel icons.
  const emojiSignature = draft.payloads.map((p) => `${p.stableKey}:${p.emoji}`).join('|')

  // ---- §8 delivery progress: same run, same selected time as the globe/timeline ------------------
  // Static per-run inputs (segments + per-output meta), memoised so scrubbing does not rebuild them.
  const delivery = useMemo(() => {
    if (!lastRun) return null
    const result = lastRun.envelope.result
    if (result.analysis_mode !== 'QUEUE_AWARE') return null
    const windowStartMs = Date.parse(lastRun.context.windowStart)
    const nameReadyByKey = new Map<string, { name: string; readyAtMs: number }>()
    for (const p of (lastRun.context.content?.payloads ?? []) as PayloadDTO[]) {
      nameReadyByKey.set(p.stable_key, {
        name: p.display_name ?? p.stable_key,
        readyAtMs: Date.parse(p.ready_at),
      })
    }
    const emojiByKey = new Map(draft.payloads.map((p) => [p.stableKey, p.emoji]))
    const metas: PayloadMeta[] = result.payload_progress.map((pp) => ({
      payloadKey: pp.payload_key,
      name: nameReadyByKey.get(pp.payload_key)?.name ?? pp.payload_key,
      emoji: emojiByKey.get(pp.payload_key) ?? '📦',
      totalBytes: pp.logical_size_bytes,
      readyAtMs: nameReadyByKey.get(pp.payload_key)?.readyAtMs ?? windowStartMs,
    }))
    return { metas, segments: toSegments(result.payload_allocations), windowStartMs }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastRun, emojiSignature])

  // The selected instant from the globe clock. Reset on a new run so old times never leak across runs.
  const [clockMs, setClockMs] = useState<number | null>(null)
  useEffect(() => setClockMs(null), [lastRun])
  const onClock = useCallback((iso: string) => setClockMs(Date.parse(iso)), [])

  const deliveryRows = useMemo(() => {
    if (!delivery) return null
    const atMs = clockMs ?? delivery.windowStartMs
    return { rows: deliveryProgressAt(delivery.segments, delivery.metas, atMs), atIso: new Date(atMs).toISOString() }
  }, [delivery, clockMs])

  // Apply the map-visibility filter here, memoised by a stable key set signature, so hiding a station
  // rebuilds the globe (a deliberate display change) but re-rendering for any other reason does not.
  const hiddenSignature = [...hiddenStationKeys].sort().join(',')
  const model = useMemo<GlobeModel>(() => {
    const filtered =
      hiddenStationKeys.size === 0
        ? baseModel
        : { ...baseModel, stations: baseModel.stations.filter((s) => !hiddenStationKeys.has(s.key)) }
    return { ...filtered, satelliteName: draft.satelliteName }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseModel, hiddenSignature])

  // Beam "flights": each output's emoji streams down its station beam while that allocation is active.
  // Kept OUT of `model` (passed as a separate prop) so changing an emoji updates entities imperatively
  // instead of rebuilding Cesium. Keyed by the emoji signature so only real emoji/run changes recompute.
  const flights = useMemo<Flight[]>(() => {
    if (!lastRun) return []
    const result = lastRun.envelope.result
    if (result.analysis_mode !== 'QUEUE_AWARE') return []
    const emojiByKey = new Map(draft.payloads.map((p) => [p.stableKey, p.emoji]))
    const built = buildFlights(result.payload_allocations, emojiByKey)
    return hiddenStationKeys.size === 0 ? built : built.filter((f) => !hiddenStationKeys.has(f.stationKey))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastRun, emojiSignature, hiddenSignature])

  return (
    <div className="globe-stage">
      <GlobePanel
        model={model}
        preview={preview}
        selectedPassKey={selectedPassKey}
        onSelectPass={onSelectPass}
        onClock={onClock}
        flights={flights}
        chaseCam={chaseCam}
        resetViewNonce={resetViewNonce}
      />
      {deliveryRows ? <DeliveryProgressPanel rows={deliveryRows.rows} atIso={deliveryRows.atIso} /> : null}
    </div>
  )
}
