// User-facing names for internal enums (spec §3-2, §6).
//
// These translate stable backend enum values into plain Korean for display. The internal value is
// NEVER changed — it still goes into the request, the hash, and the report; only the *label* shown to
// a user changes. Show the raw enum as a title/detail alongside the label where the stable key
// matters (e.g. a tooltip), so nothing is hidden, just de-emphasised.

/** Analysis mode: QUEUE_AWARE = 출력 배분 포함, NETWORK_ONLY = 전송 예산만. */
export function analysisModeLabel(mode: string): string {
  switch (mode) {
    case 'QUEUE_AWARE':
      return '출력 배분 포함'
    case 'NETWORK_ONLY':
      return '전송 예산만'
    default:
      return mode
  }
}

/** Segmentation: ATOMIC_OBJECT = 통째로 전송, FIXED_CHUNK = 나눠 전송. */
export function segmentationLabel(seg: string): string {
  switch (seg) {
    case 'ATOMIC_OBJECT':
      return '통째로 전송'
    case 'FIXED_CHUNK':
      return '나눠 전송'
    default:
      return seg
  }
}

/** One-line explanation of a segmentation choice (spec §6). */
export function segmentationHelp(seg: string): string {
  switch (seg) {
    case 'ATOMIC_OBJECT':
      return '한 세션에서 전체를 할당할 수 있어야 전송됩니다 (분할·재개 없음).'
    case 'FIXED_CHUNK':
      return '지정한 조각 크기 단위로 여러 세션에 걸쳐 전송할 수 있습니다. 조각 크기는 “패스당 전송 한도”가 아니라 조각 하나의 크기입니다.'
    default:
      return ''
  }
}

/** Service class: plain Korean for the queue grade. */
export function serviceClassLabel(cls: string): string {
  switch (cls) {
    case 'MANDATORY':
      return '필수'
    case 'PRIORITY':
      return '우선'
    case 'BEST_EFFORT':
      return '가용 시'
    default:
      return cls
  }
}
