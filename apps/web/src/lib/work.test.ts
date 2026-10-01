import { describe, expect, it, vi } from 'vitest'
import { pause, runBounded } from './work'

describe('pending submission work', () => {
  it('bounds a large batch and stops taking items after logout', async () => {
    const controller = new AbortController()
    let running = 0
    let maximum = 0
    const started: number[] = []
    const release: (() => void)[] = []
    const work = runBounded(
      Array.from({ length: 1000 }, (_, i) => i),
      3,
      controller.signal,
      async (i) => {
        started.push(i)
        maximum = Math.max(maximum, ++running)
        await new Promise<void>((resolve) => release.push(resolve))
        running--
      },
    )
    expect(started).toHaveLength(3)
    controller.abort()
    release.forEach((r) => r())
    await expect(work).rejects.toMatchObject({ name: 'AbortError' })
    expect(maximum).toBe(3)
    expect(started).toHaveLength(3)
  })
  it('interrupts retry backoff instead of waking under a new account', async () => {
    vi.useFakeTimers()
    const controller = new AbortController()
    const work = pause(30000, controller.signal)
    controller.abort()
    await expect(work).rejects.toMatchObject({ name: 'AbortError' })
    expect(vi.getTimerCount()).toBe(0)
    vi.useRealTimers()
  })
})
