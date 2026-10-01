import { describe, expect, it } from 'vitest'
import type { Job } from '../api/client'
import { bytes, expiryLabel, failureText, initials, stageOf } from './format'

function job(patch: Partial<Job>): Job {
  return {
    id: 'j1',
    attempts: 1,
    batch_id: null,
    cache_hit: false,
    cancel_requested: false,
    created_at: '2026-09-29T10:00:00Z',
    dismissed_at: null,
    document_id: 'd1',
    error_code: null,
    error_message: null,
    fingerprint: 'fp',
    finished_at: null,
    fit_skip_requested: false,
    fit_status: null,
    force: false,
    format: 'pptx',
    mode: 'mt',
    translator_id: 'mt',
    original_name: 'deck.pptx',
    progress: null,
    result_available: false,
    result_expires_at: null,
    retention: 'saved',
    source_requested: 'auto',
    source_resolved: null,
    started_at: null,
    status: 'running',
    target: 'en',
    ...patch,
  }
}

const running = (phase: string, done: number | null = null, total: number | null = null) =>
  job({ progress: { phase: phase as never, done, total, updated_at: null } })

describe('stageOf follows the progress plan labels', () => {
  it.each([
    [job({ status: 'queued' }), 'Waiting to translate'],
    [running('prepare'), 'Preparing document'],
    [running('extract'), 'Reading document'],
    [running('translate', 48, 120), 'Translating · 48 of 120 text sections'],
    [running('translate', 120, 120), 'Finishing translation'],
    [running('apply'), 'Applying translations'],
    [running('fit'), 'Translating'],
    [running('write'), 'Saving translated document'],
    [job({ status: 'succeeded', result_available: true }), 'Ready to download'],
    [job({ status: 'succeeded', result_available: false }), 'Translation unavailable'],
    [job({ status: 'failed' }), 'Translation failed'],
    [job({ status: 'cancelled' }), 'Cancelled'],
  ])('%#: %s', (j, label) => {
    expect(stageOf(j).label).toBe(label)
  })

  it('shows counts only while translating and never divides by zero', () => {
    expect(stageOf(running('translate', 3, 10)).count).toEqual({ done: 3, total: 10 })
    expect(stageOf(running('translate', 0, 0)).count).toBeNull()
    expect(stageOf(running('translate', 0, 0)).label).toBe('Translating')
    expect(stageOf(running('fit')).count).toBeNull()
  })

  it('keeps mandatory fit inside translation without controls or percentages', () => {
    expect(stageOf(running('fit')).canSkipFit).toBe(false)
    expect(stageOf(running('write')).canSkipFit).toBe(false)
    const requested = { ...running('fit'), fit_skip_requested: true }
    expect(stageOf(requested)).toMatchObject({
      label: 'Translating',
      canSkipFit: false,
    })
  })

  it('keeps cancellation requested until the service confirms it', () => {
    const j = { ...running('translate', 1, 5), cancel_requested: true }
    expect(stageOf(j)).toMatchObject({ label: 'Cancellation requested', canCancel: false })
    expect(stageOf(running('extract')).canCancel).toBe(true)
  })
})

describe('plain explanations', () => {
  it('maps known failure codes and falls back to the safe service message', () => {
    expect(failureText(job({ status: 'failed', error_code: 'no_extractable_text' }))).toMatch(
      /scan/,
    )
    const other = job({
      status: 'failed',
      error_code: 'unsupported_document',
      error_message: 'The PDF is encrypted.',
    })
    expect(failureText(other)).toBe('The PDF is encrypted.')
  })

  it('formats sizes, expiry and initials', () => {
    expect(bytes(512)).toBe('512 B')
    expect(bytes(203 * 1024)).toBe('203 KB')
    expect(bytes(20 * 1024 ** 3)).toBe('20 GB')
    expect(expiryLabel(null)).toBeNull()
    expect(expiryLabel(new Date(Date.now() + 3 * 36e5).toISOString())).toBe('Deletes within a day')
    expect(expiryLabel(new Date(Date.now() + 6.5 * 864e5).toISOString())).toBe('Deletes in 7 days')
    expect(expiryLabel(new Date(Date.now() - 1000).toISOString())).toBe('Expired')
    expect(initials('Mei Tanaka')).toBe('MT')
    expect(initials('diego')).toBe('DI')
  })
})
