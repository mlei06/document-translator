import { beforeEach, expect, it, vi } from 'vitest'
import { UploadQueue } from './uploadQueue'
import { type Doc, type Job } from '../api/client'
const mocks = vi.hoisted(() => ({ upload: vi.fn(), submit: vi.fn(), batch: vi.fn() }))
vi.mock('../api/client', () => ({
  api: { POST: mocks.batch },
  unwrap: (v: unknown) => v,
  uploadDocument: mocks.upload,
  websiteRequest: mocks.submit,
  sessionSignal: () => new AbortController().signal,
}))
function deferred<T>() {
  let resolve!: (v: T) => void
  let reject!: (v: unknown) => void
  const promise = new Promise<T>((a, b) => {
    resolve = a
    reject = b
  })
  return { promise, resolve, reject }
}
const flush = async () => {
  for (let i = 0; i < 8; i++) await Promise.resolve()
}
const file = (name: string) => new File(['hello'], name, { type: 'text/plain' })
beforeEach(() => {
  vi.resetAllMocks()
  mocks.batch.mockResolvedValue({ id: 'batch' })
  mocks.submit.mockImplementation((path: string) =>
    path.endsWith('/translations')
      ? Promise.resolve({ id: 'batch-item', job: { id: path, status: 'queued' } as Job })
      : Promise.resolve(undefined),
  )
})
it('pins slow uploads immediately; early files submit alone; later drops stay separate; double clicks cannot retarget', async () => {
  const fast = deferred<{ doc: Doc; created: boolean }>()
  const slow = deferred<{ doc: Doc; created: boolean }>()
  const later = deferred<{ doc: Doc; created: boolean }>()
  for (const d of [fast, slow, later]) mocks.upload.mockReturnValueOnce({ ...d, abort: vi.fn() })
  const accepted = vi.fn()
  const q = new UploadQueue(vi.fn(), accepted)
  q.add([file('a.txt'), file('b.txt')], ['txt'], 100)
  expect(mocks.upload).toHaveBeenCalledTimes(2)
  q.select('en')
  q.select('ja')
  expect(q.items.map((i) => i.target)).toEqual(['en', 'en'])
  q.add([file('c.txt')], ['txt'], 100)
  fast.resolve({
    doc: { id: 'a', detected_source: 'en', detection: 'detected' } as Doc,
    created: true,
  })
  await flush()
  expect(accepted).toHaveBeenCalledTimes(1)
  expect(mocks.batch.mock.calls.filter((call) => String(call[0]).endsWith('/seal'))).toHaveLength(0)
  expect(mocks.submit.mock.calls[0]?.[2]).toMatchObject({
    target: 'en',
    selection_policy: 'website_auto',
    retention: 'cached',
  })
  expect(mocks.submit.mock.calls[0]?.[2]).not.toHaveProperty('source')
  expect(q.items[2]?.target).toBeUndefined()
  slow.resolve({
    doc: { id: 'b', detected_source: null, detection: 'unknown' } as Doc,
    created: true,
  })
  await flush()
  expect(accepted).toHaveBeenCalledTimes(2)
  expect(mocks.batch.mock.calls.filter((call) => String(call[0]).endsWith('/seal'))).toHaveLength(1)
  later.resolve({ doc: { id: 'c' } as Doc, created: true })
  await flush()
  expect(accepted).toHaveBeenCalledTimes(2)
})
it('retries only the failed upload preserving its pinned target', async () => {
  const a = deferred<{ doc: Doc; created: boolean }>()
  const b = deferred<{ doc: Doc; created: boolean }>()
  const retry = deferred<{ doc: Doc; created: boolean }>()
  for (const d of [a, b, retry]) mocks.upload.mockReturnValueOnce({ ...d, abort: vi.fn() })
  const q = new UploadQueue(vi.fn(), vi.fn())
  q.add([file('a.txt'), file('b.txt')], ['txt'], 100)
  q.select('es')
  a.resolve({ doc: { id: 'a' } as Doc, created: true })
  b.reject(new Error('Interrupted'))
  await flush()
  q.retry(q.items[1]!.id)
  expect(mocks.upload).toHaveBeenCalledTimes(3)
  retry.resolve({ doc: { id: 'b' } as Doc, created: true })
  await flush()
  expect(
    mocks.submit.mock.calls.filter((c) => String(c[0]).endsWith('/translations')),
  ).toHaveLength(2)
  expect(q.items[1]?.target).toBe('es')
})
it('cancellation fences upload completion and cleans staged bytes', async () => {
  const upload = deferred<{ doc: Doc; created: boolean }>()
  const abort = vi.fn()
  mocks.upload.mockReturnValue({ ...upload, abort })
  const accepted = vi.fn()
  const q = new UploadQueue(vi.fn(), accepted)
  q.add([file('a.txt')], ['txt'], 100)
  q.select('en')
  q.cancel(q.items[0]!.id)
  upload.resolve({ doc: { id: 'a' } as Doc, created: true })
  await flush()
  expect(abort).toHaveBeenCalled()
  expect(accepted).not.toHaveBeenCalled()
  expect(mocks.submit).toHaveBeenCalledWith('/v1/documents/a', 'DELETE')
})
it('bounds uploading concurrency without imposing a total batch limit', () => {
  const upload = deferred<{ doc: Doc; created: boolean }>()
  mocks.upload.mockReturnValue({ ...upload, abort: vi.fn() })
  const q = new UploadQueue(vi.fn(), vi.fn())
  q.add(
    Array.from({ length: 250 }, (_, i) => file(`${i}.txt`)),
    ['txt'],
    100,
  )
  q.select('zh')
  expect(mocks.upload).toHaveBeenCalledTimes(3)
  expect(q.items.every((i) => i.target === 'zh')).toBe(true)
  q.dispose()
})

it('pins each default-language drop independently without retargeting older drafts or uploads', async () => {
  const uploads = Array.from({ length: 3 }, () => deferred<{ doc: Doc; created: boolean }>())
  for (const upload of uploads) mocks.upload.mockReturnValueOnce({ ...upload, abort: vi.fn() })
  const q = new UploadQueue(vi.fn(), vi.fn())
  q.add([file('manual.txt')], ['txt'], 100)
  q.add([file('chinese.txt')], ['txt'], 100, 'zh')
  q.add([file('japanese.txt')], ['txt'], 100, 'ja')
  expect(q.items.map((item) => item.target)).toEqual([undefined, 'zh', 'ja'])
  expect(q.items[1]?.batch).not.toBe(q.items[2]?.batch)
  q.select('es')
  expect(q.items.map((item) => item.target)).toEqual(['es', 'zh', 'ja'])
  for (const [index, upload] of uploads.entries())
    upload.resolve({ doc: { id: String(index) } as Doc, created: true })
  await flush()
  expect(
    mocks.submit.mock.calls
      .filter((call) => String(call[0]).endsWith('/translations'))
      .map((call) => call[2].target),
  ).toEqual(['es', 'zh', 'ja'])
})
