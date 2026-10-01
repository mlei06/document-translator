// Presentation strings mapped from stable service codes (progress plan: never server prose).
import type { Job } from '../api/client'

export const LANGUAGE_NAMES: Record<string, string> = {
  en: 'English',
  zh: 'Chinese',
  ja: 'Japanese',
  es: 'Spanish',
}

export const languageName = (code: string | null | undefined): string =>
  code ? (LANGUAGE_NAMES[code] ?? code.toUpperCase()) : 'Unknown'

export const MODE_NAMES: Record<string, string> = {
  mt: 'Quick',
  llm: 'Gemma',
}
export const MODE_HINTS: Record<string, string> = {
  mt: 'SMALL-100 machine translation, fastest',
  llm: 'Gemma language model, more natural wording',
}

export interface FileType {
  label: string
  a: string
  tag: string
  tc: string
  unit: 'Slide' | 'Page' | 'Sheet' | 'Section'
}

export const TYPES: Record<string, FileType> = {
  pptx: { label: 'PowerPoint', a: 'a PowerPoint', tag: 'PPTX', tc: 'var(--t-pptx)', unit: 'Slide' },
  docx: { label: 'Word doc', a: 'a Word doc', tag: 'DOCX', tc: 'var(--t-docx)', unit: 'Section' },
  xlsx: {
    label: 'Excel sheet',
    a: 'an Excel sheet',
    tag: 'XLSX',
    tc: 'var(--t-xlsx)',
    unit: 'Sheet',
  },
  pdf: { label: 'PDF', a: 'a PDF', tag: 'PDF', tc: 'var(--t-pdf)', unit: 'Page' },
  txt: { label: 'text file', a: 'a text file', tag: 'TXT', tc: 'var(--t-txt)', unit: 'Section' },
}

export const typeOf = (format: string): FileType =>
  TYPES[format] ?? {
    label: 'file',
    a: 'a file',
    tag: format.toUpperCase() || '?',
    tc: 'var(--t-txt)',
    unit: 'Section',
  }

export const extOf = (name: string): string =>
  (/\.([a-z0-9]+)$/i.exec(name)?.[1] ?? '').toLowerCase()

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = n / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v >= 10 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`
}

export const isTerminal = (job: Job): boolean =>
  job.status === 'succeeded' || job.status === 'failed' || job.status === 'cancelled'

/** Where a job is, per the progress plan's label table. */
export interface Stage {
  label: string
  /** Stage-only count while translating, never an overall percentage. */
  count: { done: number; total: number } | null
  tone: 'work' | 'ready' | 'failed' | 'cancelled'
  canSkipFit: boolean
  canCancel: boolean
}

export function stageOf(job: Job): Stage {
  const base = { count: null, canSkipFit: false, canCancel: false }
  if (job.status === 'succeeded')
    return job.result_available
      ? { ...base, label: 'Ready to download', tone: 'ready' }
      : { ...base, label: 'Translation unavailable', tone: 'cancelled' }
  if (job.status === 'failed') return { ...base, label: 'Translation failed', tone: 'failed' }
  if (job.status === 'cancelled') return { ...base, label: 'Cancelled', tone: 'cancelled' }
  const canCancel = !job.cancel_requested
  if (job.cancel_requested)
    return { ...base, label: 'Cancellation requested', tone: 'work', canCancel: false }
  if (job.status === 'queued')
    return { ...base, label: 'Waiting to translate', tone: 'work', canCancel }
  const p = job.progress
  switch (p?.phase) {
    case 'extract':
      return { ...base, label: 'Reading document', tone: 'work', canCancel }
    case 'translate': {
      const done = p.done ?? null
      const total = p.total ?? null
      if (done !== null && total !== null && total > 0 && done < total)
        return {
          ...base,
          label: `Translating · ${done} of ${total} text sections`,
          count: { done, total },
          tone: 'work',
          canCancel,
        }
      if (done !== null && total !== null && total > 0)
        return { ...base, label: 'Finishing translation', tone: 'work', canCancel }
      return { ...base, label: 'Translating', tone: 'work', canCancel }
    }
    case 'apply':
      return { ...base, label: 'Applying translations', tone: 'work', canCancel }
    case 'fit':
      return { ...base, label: 'Translating', tone: 'work', canCancel }
    case 'write':
      return { ...base, label: 'Saving translated document', tone: 'work', canCancel }
    default:
      return { ...base, label: 'Preparing document', tone: 'work', canCancel }
  }
}

/** A safe, plain explanation of a failed job (codes only, never stack traces). */
export function failureText(job: Job): string {
  const code = job.error_code ?? ''
  const known: Record<string, string> = {
    invalid_document: 'The file looks damaged, so it could not be read.',
    document_limit: 'The file is larger or more complex than the service accepts.',
    source_ambiguous:
      'I could not tell which language it is in. Choose the language and try again.',
    no_extractable_text: 'The file has no selectable text (it may be a scan).',
    engine_unavailable: 'The translation engine is unavailable right now. Try again later.',
    engine_response: 'The translation engine gave an unusable answer. Try again later.',
    internal_error: 'Something went wrong while translating.',
  }
  // Core document errors carry a specific message without document text (unsupported_document).
  return known[code] ?? job.error_message ?? 'Something went wrong while translating.'
}

export function whenLabel(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const yesterday = new Date(now.getTime() - 864e5)
  const day =
    d.toDateString() === now.toDateString()
      ? 'Today'
      : d.toDateString() === yesterday.toDateString()
        ? 'Yesterday'
        : d.toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })
  return `${day}, ${d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}`
}

/** "Deletes in N days" for results that expire (temporary or replaced); saved ones never do. */
export function expiryLabel(iso: string | null | undefined): string | null {
  if (!iso) return null
  const hours = (new Date(iso).getTime() - Date.now()) / 36e5
  if (hours <= 0) return 'Expired'
  if (hours < 24) return 'Deletes within a day'
  return `Deletes in ${Math.ceil(hours / 24)} days`
}

export const nFiles = (k: number): string => (k === 1 ? 'one file' : `${k} files`)
export const capital = (t: string): string => (t ? t[0]!.toUpperCase() + t.slice(1) : t)

export function initials(name: string): string {
  const parts = name.split(/[.\s_@-]+/).filter(Boolean)
  const a = parts[0]?.[0] ?? ''
  const b = parts[1]?.[0] ?? ''
  return (parts.length > 1 ? a + b : name.slice(0, 2)).toUpperCase()
}
