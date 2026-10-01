import {
  api,
  unwrap,
  uploadDocument,
  websiteRequest,
  sessionSignal,
  type Doc,
  type Job,
} from '../api/client'

export interface DraftItem {
  id: string
  file: File
  state: 'waiting' | 'uploading' | 'ready' | 'submitting' | 'accepted' | 'failed' | 'cancelled'
  sent: number
  total: number
  target?: string
  batch?: string
  doc?: Doc
  job?: Job
  error?: string
  retryable?: boolean
  abort?: () => void
}
/** A synchronous target pin is the admission boundary. Upload callbacks never select a target. */
export class UploadQueue {
  items: DraftItem[] = []
  private running = 0
  private disposed = false
  private batches = new Map<string, Promise<string>>()
  private sealed = new Set<string>()
  private changed: (items: DraftItem[]) => void
  private accepted: (job: Job) => void
  constructor(changed: (items: DraftItem[]) => void, accepted: (job: Job) => void) {
    this.changed = changed
    this.accepted = accepted
  }
  private emit() {
    if (!this.disposed) this.changed([...this.items])
  }
  add(files: File[], formats: string[], maxBytes: number, target?: string) {
    const batch = target ? crypto.randomUUID() : undefined
    for (const file of files) {
      const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
      const error = !formats.includes(extension)
        ? 'Unsupported file format.'
        : !file.size
          ? 'This file is empty.'
          : file.size > maxBytes
            ? 'This file exceeds the upload limit.'
            : undefined
      this.items.push({
        id: crypto.randomUUID(),
        file,
        target,
        batch,
        state: error ? 'failed' : 'waiting',
        retryable: !error,
        sent: 0,
        total: file.size,
        error,
      })
    }
    this.emit()
    this.pump()
  }
  select(target: string) {
    const draft = this.items.filter((i) => !i.target && i.state !== 'cancelled')
    if (!draft.length) return
    const batch = crypto.randomUUID()
    for (const item of draft) {
      item.target = target
      item.batch = batch
    }
    this.emit()
    for (const item of draft) if (item.state === 'ready') void this.submit(item)
  }
  private batch(id: string) {
    let batch = this.batches.get(id)
    if (!batch) {
      batch = unwrap(
        api.POST('/v1/batches', { body: { idempotency_key: id, label: 'Website translation' } }),
      ).then((b) => b.id)
      this.batches.set(id, batch)
      void batch.catch(() => this.batches.delete(id))
    }
    return batch
  }
  private sealFinishedBatch(batch?: string) {
    if (!batch || this.sealed.has(batch)) return
    if (
      this.items.some(
        (item) => item.batch === batch && !['accepted', 'cancelled'].includes(item.state),
      )
    )
      return
    const created = this.batches.get(batch)
    if (!created) return
    this.sealed.add(batch)
    void created
      .then((id) =>
        unwrap(
          api.POST('/v1/batches/{batch_id}/seal', {
            params: { path: { batch_id: id } },
          }),
        ),
      )
      .catch(() => this.sealed.delete(batch))
  }
  private async submit(item: DraftItem) {
    if (item.state !== 'ready' || !item.target || !item.doc || this.disposed) return
    item.state = 'submitting'
    this.emit()
    try {
      const batchId = await this.batch(item.batch!)
      if (this.disposed || this.cancelled(item)) return
      const result = await websiteRequest<Job | { job?: Job; rejection_message?: string }>(
        `/v1/documents/${encodeURIComponent(item.doc.id)}/translations`,
        'POST',
        {
          target: item.target,
          selection_policy: 'website_auto',
          retention: 'cached',
          download_semantics: 'current_shared',
          batch_id: batchId,
          client_item_id: item.id,
        },
      )
      const job = 'job' in result ? result.job : 'status' in result ? (result as Job) : undefined
      if (!job)
        throw new Error(
          'rejection_message' in result ? result.rejection_message : 'The file was not accepted.',
        )
      item.job = job
      if (this.cancelled(item) || this.disposed) {
        await unwrap(api.POST('/v1/jobs/{job_id}/cancel', { params: { path: { job_id: job.id } } }))
        return
      }
      item.state = 'accepted'
      this.accepted(job)
    } catch (error) {
      if (!this.cancelled(item) && !this.disposed) {
        item.state = 'failed'
        item.error = error instanceof Error ? error.message : 'Submission failed.'
      }
    }
    this.emit()
    this.sealFinishedBatch(item.batch)
  }
  private cancelled(item: DraftItem) {
    return item.state === 'cancelled'
  }
  private pump() {
    if (this.disposed || sessionSignal().aborted) return
    while (this.running < 3) {
      const item = this.items.find((i) => i.state === 'waiting')
      if (!item) break
      this.running++
      item.state = 'uploading'
      const upload = uploadDocument(item.file, (sent, total) => {
        item.sent = sent
        item.total = total
        this.emit()
      })
      item.abort = upload.abort
      this.emit()
      void upload.promise
        .then(({ doc }) => {
          item.doc = doc
          if (this.cancelled(item) || this.disposed) {
            void this.cleanup(doc.id)
            return
          }
          item.state = 'ready'
          this.emit()
          if (item.target) void this.submit(item)
        })
        .catch((error: unknown) => {
          if (!this.cancelled(item) && !this.disposed) {
            item.state = 'failed'
            item.error = error instanceof Error ? error.message : 'Upload failed.'
            this.emit()
          }
        })
        .finally(() => {
          item.abort = undefined
          this.running--
          this.pump()
        })
    }
  }
  retry(id: string) {
    const item = this.items.find((i) => i.id === id)
    if (!item || item.state !== 'failed' || item.retryable === false) return
    item.error = undefined
    item.state = item.doc ? 'ready' : 'waiting'
    this.emit()
    if (item.doc && item.target) void this.submit(item)
    else this.pump()
  }
  retryJob(jobId: string): boolean {
    const previous = this.items.find((i) => i.job?.id === jobId)
    if (!previous) return false
    const retry: DraftItem = {
      id: crypto.randomUUID(),
      file: previous.file,
      state: 'waiting',
      sent: 0,
      total: previous.file.size,
      target: previous.target,
      batch: crypto.randomUUID(),
    }
    this.items.push(retry)
    this.emit()
    this.pump()
    return true
  }
  cancel(id: string) {
    const item = this.items.find((i) => i.id === id)
    if (!item || item.state === 'accepted') return
    item.state = 'cancelled'
    item.abort?.()
    if (item.doc) void this.cleanup(item.doc.id)
    this.emit()
    this.sealFinishedBatch(item.batch)
  }
  dismiss(id: string) {
    this.cancel(id)
    this.items = this.items.filter((i) => i.id !== id)
    this.emit()
  }
  private async cleanup(id: string) {
    try {
      await websiteRequest(`/v1/documents/${encodeURIComponent(id)}`, 'DELETE')
    } catch {
      /* server staging TTL is the recovery bound */
    }
  }
  dispose() {
    this.disposed = true
    for (const item of this.items) if (item.state !== 'accepted') this.cancel(item.id)
  }
}
