import { describe, expect, it } from 'vitest'
import {
  analysisModeLabel,
  segmentationHelp,
  segmentationLabel,
  serviceClassLabel,
} from './labels'

describe('user-facing enum labels (spec §3-2, §6)', () => {
  it('renames analysis modes to plain Korean', () => {
    expect(analysisModeLabel('QUEUE_AWARE')).toBe('출력 배분 포함')
    expect(analysisModeLabel('NETWORK_ONLY')).toBe('전송 예산만')
  })

  it('passes an unknown mode through unchanged (no silent value change)', () => {
    expect(analysisModeLabel('SOMETHING_NEW')).toBe('SOMETHING_NEW')
  })

  it('renames segmentation and explains it', () => {
    expect(segmentationLabel('ATOMIC_OBJECT')).toBe('통째로 전송')
    expect(segmentationLabel('FIXED_CHUNK')).toBe('나눠 전송')
    expect(segmentationHelp('FIXED_CHUNK')).toContain('조각 하나의 크기')
  })

  it('renames the service class grade', () => {
    expect(serviceClassLabel('MANDATORY')).toBe('필수')
    expect(serviceClassLabel('PRIORITY')).toBe('우선')
    expect(serviceClassLabel('BEST_EFFORT')).toBe('가용 시')
  })
})
