// The one transport for the service API (ADR-017): same-origin cookie session, CSRF header on
// changes, typed from the generated OpenAPI schema, errors mapped to ApiError.
import createClient, { type Middleware } from 'openapi-fetch'
import type { components, paths } from './schema'

export type Me = components['schemas']['Me']
export type Session = components['schemas']['SessionOut']
export type Capabilities = components['schemas']['Capabilities']
export type Job = components['schemas']['JobOut']
export type JobPage = components['schemas']['JobPage']
export type Doc = components['schemas']['DocumentOut']
export type Translation = components['schemas']['TranslationOut']
export type Batch = components['schemas']['BatchOut']
export type Progress = components['schemas']['ProgressOut']
export type TranslateIn = components['schemas']['TranslateIn']

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>
  readonly retryable: boolean
  readonly retryAfter: number | null

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
    retryable = false,
    retryAfter: number | null = null,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
    this.retryable = retryable
    this.retryAfter = retryAfter
  }
}

/** A request that never reached the service (offline, DNS, reset). */
export class NetworkError extends Error {
  constructor(cause: unknown) {
    super('The service could not be reached.', { cause })
    this.name = 'NetworkError'
  }
}

let csrfToken: string | null = null
let sessionWork = new AbortController()

/** End client work immediately, before logout or a replacement session. */
export function stopSessionWork(): void {
  sessionWork.abort()
}
export function sessionSignal(): AbortSignal {
  return sessionWork.signal
}
const expiredListeners = new Set<() => void>()

export function setCsrf(token: string | null): void {
  if (token !== csrfToken || sessionWork.signal.aborted) {
    sessionWork.abort()
    sessionWork = new AbortController()
  }
  csrfToken = token
}

/** Called once per 401 on an authenticated request: the session ended or was revoked. */
export function onSessionExpired(listener: () => void): () => void {
  expiredListeners.add(listener)
  return () => expiredListeners.delete(listener)
}

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

const auth: Middleware = {
  onRequest({ request }) {
    if (UNSAFE.has(request.method) && csrfToken) request.headers.set('X-CSRF-Token', csrfToken)
    const path = new URL(request.url).pathname
    if (path.startsWith('/v1/sessions') || path === '/v1/accounts') return request
    return new Request(request, { signal: AbortSignal.any([request.signal, sessionWork.signal]) })
  },
  onResponse({ request, response }) {
    const signingIn =
      request.method === 'POST' &&
      ['/v1/sessions', '/v1/accounts'].includes(new URL(request.url).pathname)
    const probing = new URL(request.url).pathname === '/v1/sessions/current'
    if (response.status === 401 && !signingIn && !probing && !request.signal.aborted)
      expiredListeners.forEach((l) => l())
    return response
  },
}

export const api = createClient<paths>({
  baseUrl: window.location.origin,
  credentials: 'same-origin',
  fetch: (request) => globalThis.fetch(request),
})
api.use(auth)

function retryAfterOf(response: Response): number | null {
  const value = response.headers.get('Retry-After')
  const seconds = value === null ? NaN : Number(value)
  return Number.isFinite(seconds) ? seconds : null
}

export function toApiError(status: number, body: unknown, retryAfter: number | null): ApiError {
  if (body && typeof body === 'object' && 'code' in body && 'message' in body) {
    const b = body as components['schemas']['ErrorOut']
    return new ApiError(status, b.code, b.message, b.details ?? {}, b.retryable, retryAfter)
  }
  return new ApiError(status, `http_${status}`, 'The service returned an unexpected response.')
}

/** Resolve an openapi-fetch call to its data, or throw ApiError / NetworkError. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response }
  try {
    result = await call
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new NetworkError(err)
  }
  const { data, error, response } = result
  if (!response.ok) throw toApiError(response.status, error, retryAfterOf(response))
  return data as T
}

export interface Upload {
  promise: Promise<{ doc: Doc; created: boolean }>
  abort: () => void
}

/**
 * Upload one source document to the owner's library (`POST /v1/documents`). XHR rather than
 * fetch because only XHR reports upload bytes, which the progress plan shows while uploading.
 */
export function uploadDocument(
  file: File,
  onProgress: (sent: number, total: number) => void,
): Upload {
  const signal = sessionSignal()
  const xhr = new XMLHttpRequest()
  const promise = new Promise<{ doc: Doc; created: boolean }>((resolve, reject) => {
    signal.throwIfAborted()
    const abort = () => xhr.abort()
    signal.addEventListener('abort', abort, { once: true })
    xhr.onloadend = () => signal.removeEventListener('abort', abort)
    const form = new FormData()
    form.append('file', file, file.name)
    xhr.open('POST', '/v1/documents?staging=true')
    xhr.withCredentials = true
    if (csrfToken) xhr.setRequestHeader('X-CSRF-Token', csrfToken)
    xhr.responseType = 'json'
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded, e.total)
    }
    xhr.onload = () => {
      if (xhr.status === 200 || xhr.status === 201) {
        resolve({ doc: xhr.response as Doc, created: xhr.status === 201 })
        return
      }
      if (xhr.status === 401) expiredListeners.forEach((l) => l())
      const after = Number(xhr.getResponseHeader('Retry-After'))
      reject(
        toApiError(xhr.status, xhr.response, Number.isFinite(after) && after > 0 ? after : null),
      )
    }
    xhr.onerror = () => reject(new NetworkError(null))
    xhr.onabort = () => reject(new DOMException('Upload cancelled', 'AbortError'))
    xhr.send(form)
  })
  return { promise, abort: () => xhr.abort() }
}

/** Start a browser download of an owned file (the session cookie authorizes the GET). */
export function download(href: string): void {
  const a = document.createElement('a')
  a.href = href
  a.download = ''
  a.rel = 'noopener'
  document.body.append(a)
  a.click()
  a.remove()
}

export const jobFileUrl = (jobId: string) => `/v1/jobs/${encodeURIComponent(jobId)}/file`
export const originalUrl = (docId: string) => `/v1/documents/${encodeURIComponent(docId)}/original`
export const translationFileUrl = (docId: string, tid: string) =>
  `/v1/documents/${encodeURIComponent(docId)}/translations/${encodeURIComponent(tid)}/file`
/** JSON transport for the shared website contract. Uses the same session and CSRF boundary. */
export async function websiteRequest<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const signal = sessionSignal()
  let response: Response
  try {
    response = await fetch(path, {
      method,
      credentials: 'same-origin',
      signal,
      headers: {
        ...(body ? { 'Content-Type': 'application/json' } : {}),
        ...(method !== 'GET' && csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    })
  } catch (error) {
    signal.throwIfAborted()
    throw new NetworkError(error)
  }
  if (response.status === 401 && !signal.aborted) expiredListeners.forEach((l) => l())
  if (!response.ok)
    throw toApiError(
      response.status,
      await response.json().catch(() => null),
      retryAfterOf(response),
    )
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}

/** Verify availability before navigation so eviction produces an actionable UI update. */
export async function downloadCurrent(url: string): Promise<void> {
  const signal = sessionSignal()
  const response = await fetch(url, { credentials: 'same-origin', signal })
  if (response.status === 401 && !signal.aborted) expiredListeners.forEach((listener) => listener())
  if (!response.ok)
    throw toApiError(
      response.status,
      await response.json().catch(() => null),
      retryAfterOf(response),
    )
  const objectUrl = URL.createObjectURL(await response.blob())
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const name =
    /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1] ??
    /filename="([^"]+)"/i.exec(disposition)?.[1] ??
    'translation'
  const a = document.createElement('a')
  a.href = objectUrl
  a.download = decodeURIComponent(name)
  document.body.append(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000)
}
