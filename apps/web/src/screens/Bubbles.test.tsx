import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { Job } from '../api/client'
import { Bubbles } from './Bubbles'

vi.stubGlobal(
  'ResizeObserver',
  class {
    observe() {}
    disconnect() {}
  },
)
afterEach(cleanup)
const job = (patch: Partial<Job>) =>
  ({
    id: 'one',
    original_name: 'report.txt',
    format: 'txt',
    target: 'en',
    source_resolved: null,
    status: 'running',
    progress: null,
    cancel_requested: false,
    result_available: false,
    ...patch,
  }) as Job

it('downloads by clicking a ready orb even when its last progress snapshot is stale', () => {
  const onAction = vi.fn(),
    onWait = vi.fn()
  const ready = job({
    status: 'succeeded',
    result_available: true,
    progress: { phase: 'translate', done: 1, total: 100, updated_at: null },
  })
  render(<Bubbles jobs={[ready]} onWait={onWait} onAction={onAction} />)
  expect(screen.queryByText('1%')).not.toBeInTheDocument()
  expect(screen.getByText('To English · Ready')).toBeVisible()
  expect(screen.getByRole('article').querySelector('.orb-value')).toBeNull()
  expect(screen.getByRole('article').querySelector('.bubble-label')?.children).toHaveLength(2)
  fireEvent.click(screen.getByRole('button', { name: 'Download report.txt' }))
  expect(onAction).toHaveBeenCalledWith(ready, 'download')
  expect(onWait).not.toHaveBeenCalled()
})
it('unfinished clicks ask for patience while the small x cancels independently', () => {
  const onAction = vi.fn(),
    onWait = vi.fn()
  const running = job({
    fallback: 'Trying another translation service',
    progress: { phase: 'fit', done: 0, total: 1, updated_at: null },
  })
  render(<Bubbles jobs={[running]} onWait={onWait} onAction={onAction} />)
  fireEvent.click(screen.getByRole('button', { name: 'Check progress for report.txt' }))
  expect(onWait).toHaveBeenCalledOnce()
  expect(onAction).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel report.txt' }))
  expect(onAction).toHaveBeenCalledWith(running, 'cancel')
  expect(onWait).toHaveBeenCalledOnce()
  expect(screen.getByText('Trying another translation service')).toBeVisible()
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
})
it('unavailable results cannot download or anger Lenny', () => {
  const onAction = vi.fn(),
    onWait = vi.fn()
  const unavailable = job({ status: 'succeeded', result_available: false })
  render(<Bubbles jobs={[unavailable]} onWait={onWait} onAction={onAction} />)
  expect(screen.getByText(/Translation unavailable/)).toBeVisible()
  expect(screen.queryByRole('button', { name: /Download/ })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Check progress for report.txt' }))
  expect(onWait).not.toHaveBeenCalled()
  expect(onAction).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss report.txt' }))
  expect(onAction).toHaveBeenCalledWith(unavailable, 'dismiss')
})
