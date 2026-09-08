import { formatUtcClock } from '../../shared/format/time'
import type { GlobeContact } from './model'

export interface PassWindowTimelineProps {
  contacts: GlobeContact[]
  windowStartMs: number
  windowEndMs: number
  currentMs: number | null
  selectedPassKey: string | null
  onSelect: (stableKey: string) => void
}

function percentAt(value: number, start: number, end: number): number {
  const duration = end - start
  if (!Number.isFinite(value) || !Number.isFinite(duration) || duration <= 0) return 0
  return Math.min(100, Math.max(0, ((value - start) / duration) * 100))
}

function durationLabel(startMs: number, endMs: number): string {
  const totalSeconds = Math.max(0, Math.round((endMs - startMs) / 1000))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return minutes > 0 ? `${minutes}분 ${seconds}초` : `${seconds}초`
}

/**
 * Contact-window overlay aligned to the same analysis window as Cesium's clock. The proportional
 * bars show where every AOS→LOS interval sits in the day; the text chips keep short LEO passes
 * readable even when their proportional bar is only a few pixels wide. Clicking either form selects
 * the pass and lets GlobePanel move the Cesium clock to its AOS.
 */
export function PassWindowTimeline(props: PassWindowTimelineProps) {
  const { contacts, windowStartMs, windowEndMs, currentMs, selectedPassKey, onSelect } = props
  if (contacts.length === 0) return null

  const ordered = [...contacts].sort((a, b) => a.aosMs - b.aosMs || a.stableKey.localeCompare(b.stableKey))
  const selected = ordered.find((contact) => contact.stableKey === selectedPassKey) ?? null

  return (
    <section className="pass-window" aria-label="패스 구간 타임라인">
      <div className="pass-window__header">
        <strong>패스 구간</strong>
        <span className="pass-window__summary">
          {selected
            ? `${selected.stationKey} · ${formatUtcClock(selected.aosIso)}–${formatUtcClock(selected.losIso)} UTC`
            : `${ordered.length}회 · AOS → LOS (UTC)`}
        </span>
      </div>

      <div className="pass-window__chips" aria-label="패스 시각 목록">
        {ordered.map((contact, index) => (
          <button
            type="button"
            key={contact.stableKey}
            className={`pass-window__chip${selectedPassKey === contact.stableKey ? ' pass-window__chip--selected' : ''}`}
            onClick={() => onSelect(contact.stableKey)}
            title={`${contact.stationKey} · ${contact.aosIso} → ${contact.losIso} · ${durationLabel(contact.aosMs, contact.losMs)}`}
          >
            P{index + 1} {formatUtcClock(contact.aosIso)}–{formatUtcClock(contact.losIso)}
          </button>
        ))}
      </div>

      <div className="pass-window__rail" aria-hidden="true">
        {[0, 25, 50, 75, 100].map((position) => (
          <span key={position} className="pass-window__tick" style={{ left: `${position}%` }} />
        ))}
        {ordered.map((contact) => {
          const left = percentAt(contact.aosMs, windowStartMs, windowEndMs)
          const right = percentAt(contact.losMs, windowStartMs, windowEndMs)
          return (
            <button
              type="button"
              tabIndex={-1}
              key={contact.stableKey}
              className={`pass-window__segment${contact.scheduled ? ' pass-window__segment--scheduled' : ''}${selectedPassKey === contact.stableKey ? ' pass-window__segment--selected' : ''}`}
              style={{ left: `${left}%`, width: `${Math.max(0.12, right - left)}%` }}
              onClick={() => onSelect(contact.stableKey)}
              title={`P${ordered.indexOf(contact) + 1} · ${contact.stationKey} · ${formatUtcClock(contact.aosIso)}–${formatUtcClock(contact.losIso)} UTC`}
            />
          )
        })}
        {currentMs !== null ? (
          <span
            className="pass-window__now"
            style={{ left: `${percentAt(currentMs, windowStartMs, windowEndMs)}%` }}
          />
        ) : null}
      </div>
      <div className="pass-window__scale" aria-hidden="true">
        <span>00h</span><span>06h</span><span>12h</span><span>18h</span><span>24h</span>
      </div>
    </section>
  )
}
