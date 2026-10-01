import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  api,
  stopSessionWork,
  sessionSignal,
  ApiError,
  NetworkError,
  onSessionExpired,
  setCsrf,
  unwrap,
} from './client'

afterEach(() => {
  vi.unstubAllGlobals()
  setCsrf(null)
})

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  const fetchMock = vi.fn(
    async (_req: Request) =>
      new Response(body === null ? null : JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json', ...headers },
      }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('API transport', () => {
  it('sends the CSRF token on changes but not on reads', async () => {
    const fetchMock = respond(200, { id: 'j1' })
    setCsrf('token-1')
    await unwrap(api.POST('/v1/jobs/{job_id}/dismiss', { params: { path: { job_id: 'j1' } } }))
    await unwrap(api.GET('/v1/jobs/{job_id}', { params: { path: { job_id: 'j1' } } }))
    const [post, get] = fetchMock.mock.calls.map((c) => c[0])
    expect(post!.headers.get('X-CSRF-Token')).toBe('token-1')
    expect(get!.headers.get('X-CSRF-Token')).toBeNull()
    expect(post!.credentials).toBe('same-origin')
  })

  it('maps service errors, including Retry-After', async () => {
    respond(
      429,
      {
        code: 'queue_full',
        message: 'Too many queued jobs',
        details: {},
        retryable: true,
        request_id: 'r',
      },
      { 'Retry-After': '7' },
    )
    const err = await unwrap(api.GET('/v1/me')).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 429, code: 'queue_full', retryable: true, retryAfter: 7 })
  })

  it('reports an ended session once, but not for sign-in attempts', async () => {
    const expired = vi.fn()
    const stop = onSessionExpired(expired)
    respond(401, {
      code: 'unauthenticated',
      message: 'no',
      details: {},
      retryable: false,
      request_id: 'r',
    })
    await unwrap(api.GET('/v1/me')).catch(() => undefined)
    await unwrap(api.POST('/v1/sessions', { body: { key: 'dt_wrong' } })).catch(() => undefined)
    await unwrap(api.GET('/v1/sessions/current')).catch(() => undefined)
    expect(expired).toHaveBeenCalledTimes(1)
    stop()
  })

  it('distinguishes an unreachable service', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))),
    )
    await expect(unwrap(api.GET('/v1/me'))).rejects.toBeInstanceOf(NetworkError)
  })
})

it('aborts old session requests before accepting a new session', async () => {
  setCsrf('alice')
  const old = sessionSignal()
  const fetchMock = respond(200, { id: 'j1' })
  await unwrap(api.GET('/v1/me'))
  const request = fetchMock.mock.calls[0]![0]
  stopSessionWork()
  expect(old.aborted).toBe(true)
  expect(request.signal.aborted).toBe(true)
  setCsrf('bob')
  expect(sessionSignal().aborted).toBe(false)
  expect(old.aborted).toBe(true)
})
