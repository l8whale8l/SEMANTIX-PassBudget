import { memo, useEffect, useRef, useState } from 'react'

import type { GlobeModel } from './model'
import type { Flight } from './delivery'
import { PassWindowTimeline } from './PassWindowTimeline'

export interface GlobePanelProps {
  /** Prebuilt globe model. The caller (GlobeStage) memoises it so this only rebuilds Cesium when the
   *  underlying geometry actually changes — never on a panel open/close or drag. */
  model: GlobeModel
  /** Whether the model is a pre-run preview (stations only, no computed contacts/track). */
  preview: boolean
  /** The pass selected in the pass table, so the globe and the table stay in sync. */
  selectedPassKey: string | null
  /** Raised when the user picks a contact on the globe. */
  onSelectPass: (stableKey: string | null) => void
  /** Throttled (≈5 Hz, only on change) clock tick so the delivery-progress panel can track the
   *  selected instant without re-rendering the whole app each frame. Must be stable. */
  onClock?: (iso: string) => void
  /** Beam flights: each output's emoji to stream down its station beam during its transfer window.
   *  Applied imperatively (updateFlights), so changing an emoji never rebuilds Cesium. */
  flights?: Flight[]
  /** Lock the camera to a chase view behind/above the satellite (applied imperatively). */
  chaseCam?: boolean
  /** Bumping this number returns the camera to the run's first composition (보기 초기화). */
  resetViewNonce?: number
}

/**
 * 3D 지구본 (F5, 작업 공간의 배경 무대). CesiumJS를 **지연 로드**하고, Cesium Ion 없이 앱에 포함된 Natural
 * Earth II 로컬 텍스처로 지구를 그린다(외부 인터넷 차단 상태에서도 동작). 지상국은 흰색 발광 마커, 위성은
 * 아이콘과 궤도선, 백엔드가 계산한 접촉창 동안 연결선을 강조한다. 모델은 부모(GlobeStage)가 만들어 넘기며,
 * 패널 개폐·드래그로는 모델이 바뀌지 않으므로 Cesium을 재생성하지 않는다. 표현(발광·아이콘 크기 등)이
 * 계산 좌표·전송 예산을 바꾸지 않는다. WebGL/Cesium 불가 시 표 fallback으로 핵심 흐름을 유지한다.
 */
function GlobePanelImpl(props: GlobePanelProps) {
  const { model, preview, selectedPassKey, onSelectPass, onClock, flights, chaseCam, resetViewNonce } =
    props
  const flightsRef = useRef(flights)
  useEffect(() => {
    flightsRef.current = flights
  }, [flights])

  const containerRef = useRef<HTMLDivElement | null>(null)
  const controllerRef = useRef<GlobeController | null>(null)
  const onSelectRef = useRef(onSelectPass)
  useEffect(() => {
    onSelectRef.current = onSelectPass
  }, [onSelectPass])
  const onClockRef = useRef(onClock)
  useEffect(() => {
    onClockRef.current = onClock
  }, [onClock])

  const [status, setStatus] = useState<'loading' | 'ready' | 'unsupported'>('loading')
  const [errorDetail, setErrorDetail] = useState<string | null>(null)
  const [clockMs, setClockMs] = useState<number | null>(null)

  // Mount Cesium once per run geometry. A `key` at the call site remounts on a new run.
  useEffect(() => {
    let disposed = false
    const container = containerRef.current
    if (!container) return

    setStatus('loading')
    setErrorDetail(null)
    void (async () => {
      try {
        const controller = await createGlobeController(
          container,
          model,
          (key) => onSelectRef.current(key),
          (iso) => {
            const nextClockMs = Date.parse(iso)
            if (Number.isFinite(nextClockMs)) setClockMs(nextClockMs)
            onClockRef.current?.(iso)
          },
          flightsRef.current ?? [],
        )
        if (disposed) {
          controller.destroy()
          return
        }
        controllerRef.current = controller
        setStatus('ready')
      } catch (err) {
        if (disposed) return
        setErrorDetail(err instanceof Error ? err.message : String(err))
        setStatus('unsupported')
      }
    })()

    return () => {
      disposed = true
      controllerRef.current?.destroy()
      controllerRef.current = null
    }
  }, [model])

  // Reflect the pass-table selection into the globe (highlight + jump the clock to its AOS).
  useEffect(() => {
    controllerRef.current?.select(selectedPassKey)
  }, [selectedPassKey, status])

  // Apply emoji beam-flights imperatively when they change (new run or an edited emoji) — this
  // re-creates only the small flight entities, never the whole viewer.
  useEffect(() => {
    if (status === 'ready') controllerRef.current?.updateFlights(flights ?? [])
  }, [flights, status])

  // Engage/disengage the chase camera imperatively (never rebuilds Cesium). Re-applied on a new run
  // (status flips to 'ready') so the lock survives a recompute.
  useEffect(() => {
    if (status === 'ready') controllerRef.current?.setChaseCam(chaseCam ?? false)
  }, [chaseCam, status])

  // "보기 초기화": return the camera to the first composition. Skip the initial mount (nonce starts
  // undefined/0) so it only fires on an actual reset click, and re-runs whenever the nonce changes.
  const resetSeen = useRef(resetViewNonce)
  useEffect(() => {
    if (status !== 'ready') return
    if (resetSeen.current === resetViewNonce) return
    resetSeen.current = resetViewNonce
    controllerRef.current?.resetView()
  }, [resetViewNonce, status])

  return (
    <div className="globe-stage__globe">
      <div
        className="globe-viewport"
        ref={containerRef}
        aria-label="3D 지구본 (지상국·궤도·접촉)"
        role="img"
      />

      <div className="globe-notes" aria-live="polite">
        {model.stations.length === 0 ? (
          <p className="globe-note globe-note--warn" role="status">
            좌표를 가진 지상국이 없어(예: 합성 접촉) 지구본에 표시할 대상이 없습니다.
          </p>
        ) : null}
        {!preview && model.track === null && model.stations.length > 0 ? (
          <p className="globe-note globe-note--warn" role="status">
            이 궤도(TLE 또는 미지정)는 궤도선을 그리지 않습니다. 지상국·접촉만 표시됩니다.
          </p>
        ) : null}
        {model.missingStationKeys.length > 0 ? (
          <p className="globe-note globe-note--warn" role="status">
            접촉이 참조하는 지상국 {model.missingStationKeys.join(', ')}의 좌표가 현재 시나리오에
            없습니다.
          </p>
        ) : null}
      </div>

      {!preview ? (
        <PassWindowTimeline
          contacts={model.contacts}
          windowStartMs={model.windowStartMs}
          windowEndMs={model.windowEndMs}
          currentMs={clockMs}
          selectedPassKey={selectedPassKey}
          onSelect={(stableKey) => onSelectRef.current(stableKey)}
        />
      ) : null}

      {status === 'loading' ? (
        <div className="globe-overlay" role="status">
          지구본을 불러오는 중…
        </div>
      ) : null}
      {status === 'unsupported' ? (
        <div className="globe-overlay globe-overlay--fallback" role="alert">
          <p>
            이 브라우저/환경에서 3D 지구본을 표시할 수 없습니다(WebGL 미지원 등). 패스 표·일별 예산 등
            핵심 기능은 그대로 사용할 수 있습니다.
          </p>
          {errorDetail ? <p className="mono">{errorDetail}</p> : null}
          <GlobeContactFallback model={model} />
        </div>
      ) : null}
    </div>
  )
}

/** Memoised so the delivery-progress clock updates in GlobeStage (≈5 Hz) never re-render the globe —
 *  its props (memoised model, stable callbacks) are unchanged, so Cesium is never rebuilt. */
export const GlobePanel = memo(GlobePanelImpl)

/** A plain table of the same contacts, shown when the 3D view can't render (map-failure fallback). */
function GlobeContactFallback({ model }: { model: GlobeModel }) {
  if (model.contacts.length === 0) return <p>표시할 접촉이 없습니다.</p>
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th scope="col">지상국</th>
            <th scope="col">AOS (UTC)</th>
            <th scope="col">LOS (UTC)</th>
            <th scope="col">선택 다운링크</th>
          </tr>
        </thead>
        <tbody>
          {model.contacts.map((c) => (
            <tr key={c.stableKey}>
              <td className="mono">{c.stationKey}</td>
              <td className="mono">{c.aosIso}</td>
              <td className="mono">{c.losIso}</td>
              <td>{c.scheduled ? '예' : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------------------------
// Imperative Cesium controller. Kept out of React render: WebGL can't run in jsdom, so this code is
// verified in the browser, while the pure `buildGlobeModel` it consumes is unit-tested.
// ---------------------------------------------------------------------------------------------

interface GlobeController {
  select: (stableKey: string | null) => void
  updateFlights: (flights: Flight[]) => void
  /** Lock the camera to a chase view behind + above the satellite, looking along its travel; off
   *  restores free camera control. No-op when the scenario has no moving satellite (no orbit track). */
  setChaseCam: (on: boolean) => void
  /** Release the chase lock (if any) and return the camera to the run's first composition. */
  resetView: () => void
  destroy: () => void
}

async function createGlobeController(
  container: HTMLElement,
  model: GlobeModel,
  onSelect: (stableKey: string | null) => void,
  onClock: (iso: string) => void,
  initialFlights: Flight[],
): Promise<GlobeController> {
  const Cesium = await import('cesium')
  await import('cesium/Build/Cesium/Widgets/widgets.css')

  // Never contact Cesium Ion: no token, and the base layer is the bundled Natural Earth II texture.
  Cesium.Ion.defaultAccessToken = ''

  const baseLayer = Cesium.ImageryLayer.fromProviderAsync(
    Cesium.TileMapServiceImageryProvider.fromUrl(
      Cesium.buildModuleUrl('Assets/Textures/NaturalEarthII'),
    ),
    {},
  )

  const viewer = new Cesium.Viewer(container, {
    // preserveDrawingBuffer keeps the last frame readable so the view can be screenshot / exported
    // to an image; negligible cost at this scale.
    contextOptions: { webgl: { preserveDrawingBuffer: true } },
    baseLayer,
    baseLayerPicker: false, // no Ion/online imagery picker
    geocoder: false, // no online address search
    // Default ellipsoid terrain (no online terrain/buildings).
    terrainProvider: new Cesium.EllipsoidTerrainProvider(),
    sceneModePicker: false,
    navigationHelpButton: false,
    homeButton: false,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: true,
    animation: true, // built-in play/pause/speed = the TimeController
    timeline: true, // built-in scrubber = the PassTimeline
  })
  viewer.scene.globe.showGroundAtmosphere = false
  viewer.creditDisplay.container.style.color = '#ccc' // keep Cesium/Natural Earth credits visible

  const startTime = Cesium.JulianDate.fromIso8601(new Date(model.windowStartMs).toISOString())
  const stopTime = Cesium.JulianDate.fromIso8601(new Date(model.windowEndMs).toISOString())
  viewer.clock.startTime = startTime.clone()
  viewer.clock.stopTime = stopTime.clone()
  viewer.clock.currentTime = startTime.clone()
  viewer.clock.clockRange = Cesium.ClockRange.CLAMPED
  viewer.clock.multiplier = 60
  viewer.timeline.zoomTo(startTime, stopTime)

  // Surface the selected instant to React, throttled (~5 Hz) and only when the whole-second value
  // changes, so the delivery-progress panel tracks time without a per-frame full re-render.
  let lastEmitMs = 0
  let lastIso = ''
  viewer.clock.onTick.addEventListener(() => {
    const nowReal = Date.now()
    if (nowReal - lastEmitMs < 200) return
    const iso = Cesium.JulianDate.toIso8601(viewer.clock.currentTime, 0)
    if (iso === lastIso) return
    lastEmitMs = nowReal
    lastIso = iso
    onClock(iso)
  })
  onClock(Cesium.JulianDate.toIso8601(startTime, 0)) // initial

  // --- ground stations: white glowing markers -------------------------------------------------
  for (const s of model.stations) {
    const pos = Cesium.Cartesian3.fromDegrees(s.longitudeDeg, s.latitudeDeg, s.heightM)
    viewer.entities.add({
      id: `station:${s.key}`,
      name: s.key,
      position: pos,
      point: {
        pixelSize: 9,
        color: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.WHITE.withAlpha(0.35),
        outlineWidth: 10, // translucent halo → "glowing" white marker
      },
      label: {
        text: s.key,
        font: '12px sans-serif',
        fillColor: Cesium.Color.WHITE,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        pixelOffset: new Cesium.Cartesian2(0, -16),
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
      },
    })
  }

  // --- satellite icon + orbit line (display-only re-sample of the run's own orbit) --------------
  let satellitePosition: import('cesium').SampledPositionProperty | null = null
  if (model.track && model.track.length > 0) {
    const sampled = new Cesium.SampledPositionProperty() // ReferenceFrame.FIXED by default
    const trackPositions: import('cesium').Cartesian3[] = []
    for (const sample of model.track) {
      const when = Cesium.JulianDate.fromIso8601(sample.t)
      const where = new Cesium.Cartesian3(sample.ecef.x, sample.ecef.y, sample.ecef.z)
      sampled.addSample(when, where)
      trackPositions.push(where)
    }
    sampled.setInterpolationOptions({
      interpolationDegree: 5,
      interpolationAlgorithm: Cesium.LagrangePolynomialApproximation,
    })
    satellitePosition = sampled

    // Faint full orbit line.
    viewer.entities.add({
      id: 'orbit-line',
      polyline: {
        positions: trackPositions,
        width: 1.5,
        material: Cesium.Color.CYAN.withAlpha(0.5),
        arcType: Cesium.ArcType.NONE,
      },
    })
    // Moving satellite marker.
    const satelliteLabel = model.satelliteName || '위성'
    viewer.entities.add({
      id: 'satellite',
      name: satelliteLabel,
      position: sampled,
      point: { pixelSize: 8, color: Cesium.Color.CYAN, outlineColor: Cesium.Color.WHITE, outlineWidth: 1 },
      label: {
        text: satelliteLabel,
        font: '11px sans-serif',
        fillColor: Cesium.Color.CYAN,
        pixelOffset: new Cesium.Cartesian2(0, 14),
      },
    })
  }

  // --- connection lines gated by the backend contact windows ----------------------------------
  const stationById = new Map(model.stations.map((s) => [s.key, s]))
  const selectedRef = { key: null as string | null }
  for (const c of model.contacts) {
    const station = stationById.get(c.stationKey)
    if (!station || !satellitePosition) continue
    const stationPos = Cesium.Cartesian3.fromDegrees(
      station.longitudeDeg,
      station.latitudeDeg,
      station.heightM,
    )
    const aos = Cesium.JulianDate.fromIso8601(c.aosIso)
    const los = Cesium.JulianDate.fromIso8601(c.losIso)
    const activeInterval = new Cesium.TimeIntervalCollection([
      new Cesium.TimeInterval({ start: aos, stop: los }),
    ])
    const satPos = satellitePosition
    viewer.entities.add({
      id: `contact:${c.stableKey}`,
      polyline: {
        positions: new Cesium.CallbackProperty((time) => {
          const sat = satPos.getValue(time ?? viewer.clock.currentTime)
          return sat ? [stationPos, sat] : []
        }, false),
        width: c.scheduled ? 3 : 1.5,
        // Active during [AOS, LOS): bright when scheduled, dimmer when merely geometric.
        show: new Cesium.CallbackProperty(
          (time) => activeInterval.contains(time ?? viewer.clock.currentTime),
          false,
        ),
        material: new Cesium.ColorMaterialProperty(
          new Cesium.CallbackProperty(() => {
            const isSelected = selectedRef.key === c.stableKey
            const base = c.scheduled ? Cesium.Color.LIME : Cesium.Color.WHITE
            return isSelected ? Cesium.Color.YELLOW : base.withAlpha(0.9)
          }, false),
        ),
        arcType: Cesium.ArcType.NONE,
      },
    })
  }

  // --- emoji "flights": each active output's emoji streams down its station beam ----------------
  // Applied imperatively so an emoji change re-creates only these small entities. Several staggered
  // copies per flight make a continuous stream (as if flowing down the beam/"straw"); each copy loops
  // top→bottom on REAL time so it keeps moving even when the sim clock is paused, while `show` is
  // gated by the allocation's [start, end] on SIM time so an emoji appears only while that output is
  // actually being transmitted at the selected time.
  const FLOW_COPIES = 3
  const FLOW_PERIOD_MS = 1500
  let flightEntities: import('cesium').Entity[] = []
  function updateFlights(flights: Flight[]) {
    for (const e of flightEntities) viewer.entities.remove(e)
    flightEntities = []
    if (!satellitePosition) return
    const satPos = satellitePosition
    for (const f of flights) {
      const station = stationById.get(f.stationKey)
      if (!station) continue
      const stationPos = Cesium.Cartesian3.fromDegrees(
        station.longitudeDeg,
        station.latitudeDeg,
        station.heightM,
      )
      const startJ = Cesium.JulianDate.fromIso8601(new Date(f.startMs).toISOString())
      const stopJ = Cesium.JulianDate.fromIso8601(new Date(f.endMs).toISOString())
      const activeInterval = new Cesium.TimeIntervalCollection([
        new Cesium.TimeInterval({ start: startJ, stop: stopJ }),
      ])
      for (let i = 0; i < FLOW_COPIES; i++) {
        const phase = i / FLOW_COPIES
        const scratch = new Cesium.Cartesian3()
        const entity = viewer.entities.add({
          id: `flight:${f.payloadKey}:${f.stationKey}:${f.startMs}:${i}`,
          position: new Cesium.CallbackPositionProperty((time) => {
            const t = time ?? viewer.clock.currentTime
            const sat = satPos.getValue(t)
            if (!sat) return undefined
            let frac = (Date.now() % FLOW_PERIOD_MS) / FLOW_PERIOD_MS + phase
            frac -= Math.floor(frac) // wrap to [0, 1): 0 at satellite, 1 at station
            return Cesium.Cartesian3.lerp(sat, stationPos, frac, scratch)
          }, false),
          label: {
            text: f.emoji,
            font: '22px sans-serif',
            show: new Cesium.CallbackProperty(
              (time) => activeInterval.contains(time ?? viewer.clock.currentTime),
              false,
            ),
            showBackground: true, // a dark pill so the emoji reads on any terrain
            backgroundColor: Cesium.Color.BLACK.withAlpha(0.55),
            backgroundPadding: new Cesium.Cartesian2(5, 4),
            disableDepthTestDistance: Number.POSITIVE_INFINITY, // draw in front of the globe
            verticalOrigin: Cesium.VerticalOrigin.CENTER,
            horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
          },
        })
        flightEntities.push(entity)
      }
    }
  }
  updateFlights(initialFlights)

  // Click a contact line / station to select the corresponding pass.
  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas)
  handler.setInputAction((movement: { position: import('cesium').Cartesian2 }) => {
    const picked = viewer.scene.pick(movement.position)
    const id: string | undefined = picked?.id?.id
    if (typeof id === 'string' && id.startsWith('contact:')) {
      onSelect(id.slice('contact:'.length))
    } else {
      onSelect(null)
    }
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK)

  // Frame the Earth centred on the stations' longitude, from a fixed altitude. (Fitting all
  // entities would pull the camera back to enclose the whole 7000 km-radius orbit line.) Kept as a
  // function so "보기 초기화" can return to exactly this first composition.
  function applyInitialView() {
    if (model.stations.length === 0) return
    const meanLon = model.stations.reduce((sum, s) => sum + s.longitudeDeg, 0) / model.stations.length
    const meanLat = model.stations.reduce((sum, s) => sum + s.latitudeDeg, 0) / model.stations.length
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(meanLon, meanLat, 15_000_000),
    })
  }
  applyInitialView()

  // Dev-only handle so the globe can be driven from the console / automated checks. Stripped from
  // production builds by the bundler (import.meta.env.DEV is false there).
  if (import.meta.env.DEV) {
    ;(window as unknown as { __pbGlobe?: unknown }).__pbGlobe = { viewer, model, Cesium }
  }

  // --- chase camera: FOLLOW the satellite at a CONSTANT range, direction rotatable -----------------
  // Each frame the camera is placed at satellite + offset, where the offset is a fixed-length vector in
  // the satellite's local velocity/radial frame (forward F, right R, radial up U). Left-drag rotates
  // the offset's azimuth/elevation and the wheel changes its length — so the range to the satellite
  // stays fixed while the view direction is free (Cesium's own trackedEntity does not hold a range).
  const CHASE_BACK_M = 450_000 // initial offset behind (anti-velocity)
  const CHASE_UP_M = 950_000 // initial offset above, radial (≈65° below horizontal)
  const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, x))
  let chaseRange = Math.hypot(CHASE_BACK_M, CHASE_UP_M) // ~1051 km, kept constant on rotate
  let chaseAz = Math.PI // 180° → behind (anti-velocity)
  let chaseEl = Math.atan2(CHASE_UP_M, CHASE_BACK_M) // ~65° above the local horizon
  let chaseListener: (() => void) | null = null
  let chaseHandler: import('cesium').ScreenSpaceEventHandler | null = null
  function stopChase() {
    if (chaseListener) {
      viewer.scene.preRender.removeEventListener(chaseListener)
      chaseListener = null
    }
    if (chaseHandler) {
      chaseHandler.destroy()
      chaseHandler = null
    }
  }
  function setChaseCam(on: boolean) {
    stopChase()
    if (!on || !satellitePosition) {
      viewer.scene.screenSpaceCameraController.enableInputs = true
      return
    }
    const satPos = satellitePosition
    viewer.scene.screenSpaceCameraController.enableInputs = false // we drive the camera ourselves

    // Custom rotate/zoom: left-drag swings azimuth/elevation, wheel changes range (all keep following).
    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas)
    chaseHandler = handler
    let dragging = false
    let lastX = 0
    let lastY = 0
    handler.setInputAction((e: { position: import('cesium').Cartesian2 }) => {
      dragging = true
      lastX = e.position.x
      lastY = e.position.y
    }, Cesium.ScreenSpaceEventType.LEFT_DOWN)
    handler.setInputAction(() => {
      dragging = false
    }, Cesium.ScreenSpaceEventType.LEFT_UP)
    handler.setInputAction((m: { endPosition: import('cesium').Cartesian2 }) => {
      if (!dragging) return
      chaseAz -= (m.endPosition.x - lastX) * 0.006
      chaseEl = clamp(chaseEl + (m.endPosition.y - lastY) * 0.006, 0.17, 1.48) // ~10°..85°
      lastX = m.endPosition.x
      lastY = m.endPosition.y
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE)
    handler.setInputAction((delta: number) => {
      chaseRange = clamp(chaseRange * (delta > 0 ? 0.9 : 1.1), 120_000, 8_000_000)
    }, Cesium.ScreenSpaceEventType.WHEEL)

    chaseListener = () => {
      const time = viewer.clock.currentTime
      const p = satPos.getValue(time)
      if (!p) return
      const pNext = satPos.getValue(Cesium.JulianDate.addSeconds(time, 1, new Cesium.JulianDate()))
      const U = Cesium.Cartesian3.normalize(p, new Cesium.Cartesian3()) // radial up
      // forward F = velocity projected perpendicular to U (fallback +X)
      let F = pNext
        ? Cesium.Cartesian3.subtract(pNext, p, new Cesium.Cartesian3())
        : Cesium.Cartesian3.clone(Cesium.Cartesian3.UNIT_X, new Cesium.Cartesian3())
      const fdotU = Cesium.Cartesian3.dot(F, U)
      F = Cesium.Cartesian3.normalize(
        Cesium.Cartesian3.subtract(F, Cesium.Cartesian3.multiplyByScalar(U, fdotU, new Cesium.Cartesian3()), F),
        F,
      )
      const R = Cesium.Cartesian3.normalize(Cesium.Cartesian3.cross(F, U, new Cesium.Cartesian3()), new Cesium.Cartesian3())
      // offset direction from azimuth (around U) + elevation (above local horizon)
      const horiz = Cesium.Cartesian3.add(
        Cesium.Cartesian3.multiplyByScalar(F, Math.cos(chaseAz), new Cesium.Cartesian3()),
        Cesium.Cartesian3.multiplyByScalar(R, Math.sin(chaseAz), new Cesium.Cartesian3()),
        new Cesium.Cartesian3(),
      )
      const offDir = Cesium.Cartesian3.add(
        Cesium.Cartesian3.multiplyByScalar(horiz, Math.cos(chaseEl), new Cesium.Cartesian3()),
        Cesium.Cartesian3.multiplyByScalar(U, Math.sin(chaseEl), new Cesium.Cartesian3()),
        new Cesium.Cartesian3(),
      )
      const cam = Cesium.Cartesian3.add(
        p,
        Cesium.Cartesian3.multiplyByScalar(offDir, chaseRange, new Cesium.Cartesian3()),
        new Cesium.Cartesian3(),
      )
      const dir = Cesium.Cartesian3.normalize(Cesium.Cartesian3.subtract(p, cam, new Cesium.Cartesian3()), new Cesium.Cartesian3())
      viewer.camera.setView({ destination: cam, orientation: { direction: dir, up: U } })
    }
    viewer.scene.preRender.addEventListener(chaseListener)
    viewer.clock.shouldAnimate = true // motion is the point of a chase view
  }

  return {
    select(stableKey: string | null) {
      selectedRef.key = stableKey
      if (!stableKey) return
      const contact = model.contacts.find((c) => c.stableKey === stableKey)
      if (contact) {
        // Jump the clock to the pass so its connection line is visible.
        viewer.clock.currentTime = Cesium.JulianDate.fromIso8601(contact.aosIso)
        viewer.clock.shouldAnimate = false
      }
    },
    updateFlights,
    setChaseCam,
    resetView() {
      setChaseCam(false) // release the lock + re-enable inputs
      applyInitialView() // back to the first composition
    },
    destroy() {
      stopChase()
      handler.destroy()
      if (!viewer.isDestroyed()) viewer.destroy()
    },
  }
}
