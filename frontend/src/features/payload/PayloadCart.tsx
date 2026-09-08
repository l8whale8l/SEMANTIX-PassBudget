import { useState } from 'react'

import type { PayloadForm, Segmentation, ServiceClass } from '../scenario/draft'
import { UnitField } from '../../shared/ui/UnitField'
import { AssumptionBadge } from '../../shared/ui/AssumptionBadge'
import { bytesStringToAdaptiveHint } from '../../shared/format/units'
import { segmentationLabel, segmentationHelp, serviceClassLabel } from '../../shared/format/labels'

export interface PayloadCartProps {
  payloads: PayloadForm[]
  patchPayload: (editId: string, partial: Partial<PayloadForm>) => void
  removePayload: (editId: string) => void
  analysisMode: 'NETWORK_ONLY' | 'QUEUE_AWARE'
  /** Payload stable keys referenced by a dependency — their delete/rename is blocked. */
  referencedKeys: Set<string>
  /** Human list of the dependencies that reference a given payload key. */
  referencingText: (key: string) => string
  /** Optional controlled selection so the left sidebar can open a specific output's detail here.
   *  When omitted, the cart keeps its own internal selection (its unit tests rely on this). */
  selectedEditId?: string | null
  onSelectEditId?: (editId: string | null) => void
}

const SERVICE_CLASSES: ServiceClass[] = ['MANDATORY', 'PRIORITY', 'BEST_EFFORT']
const EMOJI_CHOICES = ['🛰️', '📦', '🔥', '🚢', '✈️', '🌊', '🗺️', '📡', '🎥', '📈', '🛢️', '🌎', '📷', '⚡']

/**
 * The model-output cart as a list + detail (spec §6). Each row is a compact summary (name, transfer
 * size, grade/priority, split method, size source); selecting a row opens that output's detail editor
 * — one at a time, instead of every output's full form stacked. Storage occupancy and other advanced
 * leaves live under “고급 편집”. The size-source label changes to “직접 수정” once a measured size is
 * hand-edited, so a measured value is never mislabelled as still-measured.
 */
export function PayloadCart({
  payloads,
  removePayload,
  analysisMode,
  referencedKeys,
  selectedEditId,
  onSelectEditId,
}: PayloadCartProps) {
  const [internalId, setInternalId] = useState<string | null>(null)
  const selectedId = selectedEditId !== undefined ? selectedEditId : internalId
  const setSelectedId = onSelectEditId ?? setInternalId
  const excluded = analysisMode === 'NETWORK_ONLY'

  return (
    <fieldset className="card">
      <legend>모델 출력 장바구니 ({payloads.length})</legend>
      {excluded ? (
        <p className="hint hint--warn" role="status">
          NETWORK_ONLY 실행에서는 출력물이 계산 대상에서 제외됩니다. 초안은 보존되며 QUEUE_AWARE에서
          다시 반영됩니다.
        </p>
      ) : null}

      {payloads.length === 0 ? (
        <p className="hint">
          장바구니가 비어 있습니다. 위 “출력 추가”에서 붙여넣기·파일·가정 크기로 추가하세요.
          {analysisMode === 'QUEUE_AWARE' ? ' QUEUE_AWARE 실행에는 최소 한 개가 필요합니다.' : null}
        </p>
      ) : (
        <ul className="payloadrows">
          {payloads.map((p) => {
            const referenced = referencedKeys.has(p.stableKey)
            const sizeHint = bytesStringToAdaptiveHint(p.logicalSizeBytes) ?? `${p.logicalSizeBytes} B?`
            return (
              <li
                key={p.editId}
                className={
                  'payloadrow' +
                  (excluded ? ' payloadrow--excluded' : '') +
                  (p.editId === selectedId ? ' payloadrow--selected' : '')
                }
              >
                <button
                  type="button"
                  className="payloadrow__name"
                  onClick={() => setSelectedId(p.editId)}
                  aria-expanded={p.editId === selectedId}
                  title="편집 — 오른쪽 상세 창 열기"
                >
                  <span className="payloadrow__emoji" aria-hidden="true">{p.emoji}</span>{' '}
                  {p.displayName || p.stableKey}
                </button>
                <span className="payloadrow__size" title={`${p.logicalSizeBytes} B`}>{sizeHint}</span>
                <span className="payloadrow__grade">
                  {serviceClassLabel(p.serviceClass)} · 우선 {p.missionPriority}
                </span>
                <span className="payloadrow__seg">{segmentationLabel(p.segmentation)}</span>
                <span className="payloadrow__src hint">{p.sizeSource}</span>
                {excluded ? <AssumptionBadge tone="warn" label="실행 제외" /> : null}
                {referenced ? <AssumptionBadge tone="warn" label="의존성 참조됨" /> : null}
                <button
                  type="button"
                  className="btn btn--danger payloadrow__remove"
                  onClick={() => removePayload(p.editId)}
                  disabled={referenced}
                  title={referenced ? '먼저 참조 중인 의존성을 제거하세요' : undefined}
                >
                  제거
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {payloads.length > 0 ? (
        <p className="hint">이름을 누르면 오른쪽에 상세 편집 창이 열립니다.</p>
      ) : null}
    </fieldset>
  )
}

export interface PayloadDetailProps {
  payload: PayloadForm
  onPatch: (partial: Partial<PayloadForm>) => void
  excluded: boolean
  referenced: boolean
  referencingText: string
}

/** The per-output detail editor, shown in a companion panel beside the cart (not inline). */
export function PayloadDetail({ payload, onPatch, excluded, referenced, referencingText }: PayloadDetailProps) {
  const logicalHint = bytesStringToAdaptiveHint(payload.logicalSizeBytes)
  const storageHint = bytesStringToAdaptiveHint(payload.storageSizeBytes)
  const sizesEqual = payload.logicalSizeBytes === payload.storageSizeBytes
  return (
    <div className={`payload-detail${excluded ? ' payload-detail--excluded' : ''}`}>
      <div className="payload-detail__head">
        <h4 className="payload-detail__title">출력 상세</h4>
      </div>

      {referenced ? (
        <p className="hint hint--warn" role="status">
          이 출력물은 의존성에서 참조됩니다({referencingText}). 삭제·이름 변경 전에 “출력 의존성”에서 해당
          의존성을 먼저 제거하세요.
        </p>
      ) : null}

      <div className="row">
        <UnitField
          label="표시 이름"
          value={payload.displayName}
          onChange={(v) => onPatch({ displayName: v })}
        />
        <UnitField
          label="stable key"
          monospace
          value={payload.stableKey}
          disabled={referenced}
          help={referenced ? '의존성이 참조 중이라 잠김' : undefined}
          onChange={(v) => onPatch({ stableKey: v })}
        />
      </div>

      <div className="payload-emoji">
        <label className="payload-emoji__label">지도 이모지</label>
        <div className="payload-emoji__picks">
          {EMOJI_CHOICES.map((e) => (
            <button
              key={e}
              type="button"
              className={payload.emoji === e ? 'payload-emoji__btn payload-emoji__btn--on' : 'payload-emoji__btn'}
              onClick={() => onPatch({ emoji: e })}
              aria-pressed={payload.emoji === e}
            >
              {e}
            </button>
          ))}
          <input
            className="payload-emoji__input"
            value={payload.emoji}
            maxLength={4}
            onChange={(ev) => onPatch({ emoji: ev.target.value })}
            aria-label="이모지 직접 입력"
            title="이모지 직접 입력"
          />
        </div>
        <p className="unit-field__help">전송 중일 때 이 이모지가 위성→지상국 빔을 타고 내려갑니다(표시만, 계산 불변).</p>
      </div>

      <p className="hint">크기 출처: {payload.sizeSource}</p>
      <UnitField
        label="전송 크기(논리)"
        unit="bytes"
        inputMode="numeric"
        help={logicalHint ? `${logicalHint} · 수정하면 ‘가정값’으로 표시됩니다` : '정수 바이트를 입력하세요'}
        value={payload.logicalSizeBytes}
        onChange={(v) => onPatch({ logicalSizeBytes: v, sizeSource: `직접 수정(가정값, ${v} B)` })}
      />

      <div className="row">
        <div className="unit-field">
          <label>서비스 등급</label>
          <select
            value={payload.serviceClass}
            onChange={(e) => onPatch({ serviceClass: e.target.value as ServiceClass })}
          >
            {SERVICE_CLASSES.map((c) => (
              <option key={c} value={c}>
                {serviceClassLabel(c)} ({c})
              </option>
            ))}
          </select>
        </div>
        <UnitField
          label="임무 우선순위"
          unit="0..100, 클수록 우선"
          inputMode="numeric"
          value={payload.missionPriority}
          onChange={(v) => onPatch({ missionPriority: v })}
        />
      </div>

      <div className="unit-field">
        <label>분할 방식</label>
        <select
          value={payload.segmentation}
          onChange={(e) => onPatch({ segmentation: e.target.value as Segmentation })}
        >
          <option value="ATOMIC_OBJECT">{segmentationLabel('ATOMIC_OBJECT')} (ATOMIC_OBJECT)</option>
          <option value="FIXED_CHUNK">{segmentationLabel('FIXED_CHUNK')} (FIXED_CHUNK)</option>
        </select>
        <p className="unit-field__help">{segmentationHelp(payload.segmentation)}</p>
      </div>

      {payload.segmentation === 'FIXED_CHUNK' ? (
        <UnitField
          label="조각 하나의 크기"
          unit="bytes"
          help="‘패스당 전송 한도’가 아니라 조각 하나의 크기입니다. FIXED_CHUNK은 재개 가능 전송이 필요합니다(resume_supported=true 자동)."
          inputMode="numeric"
          value={payload.chunkSizeBytes}
          onChange={(v) => onPatch({ chunkSizeBytes: v })}
        />
      ) : null}

      <details className="payload-advanced">
        <summary>고급 편집 (저장 점유·큐 순번)</summary>
        <UnitField
          label="저장 점유 크기"
          unit="bytes"
          help={
            (storageHint ? `${storageHint}` : '정수 바이트') +
            (sizesEqual ? ' · 전송 크기와 동일' : ' · 전송 크기와 다름')
          }
          inputMode="numeric"
          value={payload.storageSizeBytes}
          onChange={(v) => onPatch({ storageSizeBytes: v })}
        />
        <UnitField
          label="큐 순번"
          unit="queue_sequence"
          inputMode="numeric"
          value={payload.queueSequence}
          onChange={(v) => onPatch({ queueSequence: v })}
        />
      </details>
    </div>
  )
}
