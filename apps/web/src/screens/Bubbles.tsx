import { useLayoutEffect, useRef, useState, type CSSProperties, type RefObject } from 'react'
import type { Job } from '../api/client'
import { failureText, isTerminal, languageName, stageOf } from '../lib/format'
import { FileIcon } from '../ui/FileIcon'
import { big, mouthCenter, spitFrames, reducedMotion } from '../lib/motion'

export function Bubbles({
  jobs,
  fresh,
  onWait,
  onAction,
}: {
  jobs: Job[]
  fresh?: RefObject<Set<string>>
  onWait: () => void
  onAction: (job: Job, kind: 'download' | 'cancel' | 'dismiss' | 'retry') => void
}) {
  const root = useRef<HTMLElement>(null)
  const seen = useRef(new Set<string>())
  const [slots, setSlots] = useState<{ x: number; y: number }[]>([])
  const [page, setPage] = useState(0)
  // Keep the prototype's centre-out placement; page excess files rather than overlapping them.
  useLayoutEffect(() => {
    const stage = root.current?.parentElement
    if (!stage) return
    const layout = () => {
      const width = stage.clientWidth,
        height = stage.clientHeight
      if (width <= 1000 || innerHeight <= 500) {
        setSlots([])
        return
      }
      const columns = Math.max(1, Math.floor((width / 2 - 220) / 150))
      const rows = Math.max(1, Math.floor((height - 56) / 180))
      const actor = document.getElementById('lennyBtn')?.getBoundingClientRect()
      const center = actor
        ? actor.top + actor.height / 2 - stage.getBoundingClientRect().top
        : height / 2
      const ys = Array.from({ length: rows }, (_, i) => 24 + i * 180).sort(
        (a, b) => Math.abs(a + 60 - center) - Math.abs(b + 60 - center),
      )
      const positions = []
      for (let col = 0; col < columns; col++)
        for (const y of ys)
          for (const side of [-1, 1])
            positions.push({ x: width / 2 + side * (290 + col * 150) - 70, y })
      setSlots(positions)
    }
    layout()
    const observer = new ResizeObserver(layout)
    observer.observe(stage)
    return () => observer.disconnect()
  }, [])
  const capacity = slots.length || Math.max(1, jobs.length)
  const pages = Math.max(1, Math.ceil(jobs.length / capacity))
  const currentPage = Math.min(page, pages - 1)
  useLayoutEffect(() => {
    for (const element of root.current?.querySelectorAll<HTMLElement>(
      '[data-job-id]:not([hidden])',
    ) ?? []) {
      const id = element.dataset.jobId!
      if (seen.current.has(id)) continue
      seen.current.add(id)
      const actor = big()
      if (!fresh?.current.delete(id) || !actor || reducedMotion()) continue
      const orb = element.querySelector('.status-orb')!.getBoundingClientRect()
      const from = mouthCenter(actor)
      element.animate(
        spitFrames(from.x - orb.left - orb.width / 2, from.y - orb.top - orb.height / 2),
        {
          duration: 800,
          easing: 'cubic-bezier(.3,.6,.4,1)',
        },
      )
    }
  }, [jobs, fresh, slots, currentPage])
  return (
    <>
      <section
        ref={root}
        className="translation-bubbles constellation"
        aria-label="Translation queue"
      >
        {jobs.map((job, index) => {
          const stage = stageOf(job)
          const terminal = isTerminal(job)
          const ready = job.status === 'succeeded' && job.result_available
          const percent = stage.count
            ? Math.floor((stage.count.done / stage.count.total) * 100)
            : null
          const shortStatus = ready
            ? 'Ready'
            : job.status === 'failed'
              ? 'Retry'
              : job.status === 'cancelled'
                ? 'Cancelled'
                : job.status === 'succeeded'
                  ? 'Unavailable'
                  : job.cancel_requested
                    ? 'Cancelling'
                    : job.status === 'queued'
                      ? 'Queued'
                      : job.progress?.phase === 'write'
                        ? 'Saving'
                        : job.progress?.phase === 'extract'
                          ? 'Reading'
                          : job.progress
                            ? 'Translating'
                            : 'Preparing'
          const slot = slots[index % capacity]
          const label = ready
            ? `Download ${job.original_name}`
            : job.status === 'failed'
              ? `Retry ${job.original_name}`
              : `Check progress for ${job.original_name}`
          const detail =
            job.status === 'failed'
              ? failureText(job)
              : job.status === 'succeeded' && !ready
                ? 'Translation unavailable. Upload the original again.'
                : job.fallback && !terminal
                  ? job.fallback
                  : stage.label
          return (
            <article
              className={`translation-bubble ${stage.tone}`}
              key={job.id}
              data-job-id={job.id}
              aria-label={job.original_name}
              hidden={!!slots.length && Math.floor(index / capacity) !== currentPage}
              style={
                { left: slot?.x, top: slot?.y, '--fd': `${-(index % 7) * 0.7}s` } as CSSProperties
              }
            >
              <div className="bubble-float">
                <button
                  className="bubble-open"
                  aria-label={label}
                  title={`${job.original_name}\n${languageName(job.source_resolved)} → ${languageName(job.target)}\n${detail}`}
                  data-ready={ready || undefined}
                  onClick={() =>
                    ready
                      ? onAction(job, 'download')
                      : job.status === 'failed'
                        ? onAction(job, 'retry')
                        : !terminal
                          ? onWait()
                          : undefined
                  }
                >
                  <span
                    className={`status-orb orb ${stage.tone}${!terminal && percent === null ? ' indeterminate' : ''}`}
                  >
                    <svg viewBox="0 0 100 100" aria-hidden="true">
                      <circle className="track" cx="50" cy="50" r="44" />
                      <circle
                        className="progress"
                        cx="50"
                        cy="50"
                        r="44"
                        pathLength="100"
                        strokeDasharray={`${ready ? 100 : terminal ? 0 : (percent ?? 24)} 100`}
                      />
                    </svg>
                    <FileIcon format={job.format} />
                    {!terminal && percent !== null ? (
                      <span className="orb-value">{percent}%</span>
                    ) : null}
                    {ready ? (
                      <span className="orb-ready" aria-hidden="true">
                        ✓
                      </span>
                    ) : null}
                  </span>
                  <span className="bubble-label">
                    <span className="bubble-name" title={job.original_name}>
                      {job.original_name}
                    </span>
                    <span className="bubble-summary">
                      To {languageName(job.target)} · {shortStatus}
                    </span>
                    {job.status === 'failed' ||
                    (job.status === 'succeeded' && !ready) ||
                    (job.fallback && !terminal) ? (
                      <span className="bubble-detail bubble-problem">{detail}</span>
                    ) : null}
                  </span>
                </button>
                <button
                  className="bubble-close"
                  aria-label={`${terminal ? 'Dismiss' : 'Cancel'} ${job.original_name}`}
                  title={terminal ? 'Move to History' : 'Cancel translation'}
                  disabled={job.cancel_requested && !terminal}
                  onClick={() => onAction(job, terminal ? 'dismiss' : 'cancel')}
                >
                  ×
                </button>
              </div>
            </article>
          )
        })}
      </section>
      {pages > 1 ? (
        <nav className="bubble-pages" aria-label="Bubble pages">
          <button
            className="icon-btn"
            aria-label="Previous bubbles"
            disabled={!currentPage}
            onClick={() => setPage(currentPage - 1)}
          >
            ‹
          </button>
          <span aria-live="polite">
            {currentPage + 1} / {pages}
          </span>
          <button
            className="icon-btn"
            aria-label="Next bubbles"
            disabled={currentPage === pages - 1}
            onClick={() => setPage(currentPage + 1)}
          >
            ›
          </button>
        </nav>
      ) : null}
    </>
  )
}
