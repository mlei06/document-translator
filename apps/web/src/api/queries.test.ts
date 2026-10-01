import { afterEach, expect, it, vi } from 'vitest'
import { fetchActiveJobs } from './queries'
import { setCsrf } from './client'

afterEach(() => vi.unstubAllGlobals())
it('finds old running work beyond 200 newer completed jobs', async () => {
  setCsrf('test')
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      calls.push(request.url)
      const second = new URL(request.url).searchParams.get('cursor')
      return Response.json(
        second
          ? { items: [{ id: 'old', status: 'running' }], next_cursor: null }
          : {
              items: Array.from({ length: 200 }, (_, i) => ({
                id: String(i),
                status: 'succeeded',
              })),
              next_cursor: 'next',
            },
      )
    }),
  )
  const jobs = await fetchActiveJobs()
  expect(jobs).toHaveLength(201)
  expect(jobs.at(-1)?.status).toBe('running')
  expect(calls[1]).toContain('cursor=next')
})
