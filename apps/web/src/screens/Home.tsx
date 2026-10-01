import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, downloadCurrent, jobFileUrl, unwrap, type Job, type Me } from '../api/client'
import { useActiveJobs, useCapabilities, refreshWork } from '../api/queries'
import { WorkspaceContext, type Workspace } from '../app/workspace'
import { UploadQueue, type DraftItem } from '../app/uploadQueue'
import { Lenny } from '../lenny/Lenny'
import { Speech, type Line } from '../lenny/Speech'
import { languageName, TYPES, isTerminal, extOf, typeOf } from '../lib/format'
import {
  registerBigLenny,
  flyCard,
  mouthCenter,
  setOpen,
  mood,
  boop,
  cheer,
  burstAt,
  pointer,
  track,
  reducedMotion,
  tossToHistory,
} from '../lib/motion'
import { FileIcon } from '../ui/FileIcon'
import { LennyMenu } from './Menus'
import { useSettings } from '../lib/settings'
import { Header } from './Header'
import { History } from './History'
import { SettingsSheet } from './SettingsSheet'
import { Bubbles } from './Bubbles'

export function Home({
  me,
  arriving,
  onSignOut,
}: {
  me: Me
  arriving: boolean
  onSignOut: () => void
}) {
  const qc = useQueryClient()
  const caps = useCapabilities()
  const settings = useSettings()
  const [items, setItems] = useState<DraftItem[]>([])
  const [localJobs, setLocalJobs] = useState<Map<string, Job>>(() => new Map())
  const [hidden, setHidden] = useState<Set<string>>(() => new Set())
  const [history, setHistory] = useState(false)
  const [preferences, setPreferences] = useState(false)
  const [message, setMessage] = useState('')
  const [line, setLine] = useState<Line | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [impatient, setImpatient] = useState(false)
  const patienceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const button = useRef<HTMLButtonElement>(null)
  const feeding = useRef(0)
  const previous = useRef(new Map<string, string>())
  const fresh = useRef(new Set<string>())
  const picker = useRef<HTMLInputElement>(null)
  const uploadList = useRef<HTMLElement>(null)
  const lastFailures = useRef(new Set<string>())
  const lenny = useRef<SVGSVGElement>(null)
  const queue = useRef<UploadQueue | null>(null)
  const active = useActiveJobs(
    items.some((i) => !!i.target && !['accepted', 'failed', 'cancelled'].includes(i.state)),
  )
  useEffect(() => {
    const q = new UploadQueue(setItems, (j) => {
      fresh.current.add(j.id)
      setLocalJobs((prev) => new Map(prev).set(j.id, j))
      refreshWork(qc)
    })
    queue.current = q
    return () => {
      q.dispose()
      queue.current = null
    }
  }, [qc])
  useEffect(() => {
    registerBigLenny(() => lenny.current)
    return () => {
      registerBigLenny(() => null)
      if (patienceTimer.current) clearTimeout(patienceTimer.current)
      pointer.dragging = false
      document.body.classList.remove('dragging')
    }
  }, [])
  useEffect(() => {
    let last = performance.now()
    const wake = () => {
      last = performance.now()
      if (lenny.current?.classList.contains('sleep')) boop(lenny.current)
      lenny.current?.classList.remove('sleep')
    }
    const events = [
      'pointermove',
      'pointerdown',
      'keydown',
      'dragenter',
      'wheel',
      'touchstart',
    ] as const
    events.forEach((event) => window.addEventListener(event, wake))
    const timer = window.setInterval(() => {
      if (
        !reducedMotion() &&
        performance.now() - last > 40000 &&
        !feeding.current &&
        !document.querySelector('[role="dialog"], #lmenu:not([hidden])')
      )
        lenny.current?.classList.add('sleep')
    }, 2000)
    return () => {
      clearInterval(timer)
      events.forEach((event) => window.removeEventListener(event, wake))
    }
  }, [])
  useEffect(() => {
    for (const job of active.data ?? []) {
      const before = previous.current.get(job.id)
      if (before && before !== job.status && job.status === 'succeeded') {
        cheer(lenny.current)
        burstAt(document.querySelector(`[data-job-id="${job.id}"] .status-orb`))
      }
      previous.current.set(job.id, job.status)
    }
  }, [active.data])
  const jobs = new Map(localJobs)
  for (const job of active.data ?? []) jobs.set(job.id, job)
  const visible = [...jobs.values()].filter((j) => !hidden.has(j.id))
  const draft = items.filter((i) => !i.target && i.state !== 'cancelled')
  const staged = items.filter((i) => i.state !== 'accepted' && i.state !== 'cancelled')
  useEffect(() => {
    const failed = items.filter((item) => item.state === 'failed')
    const newlyFailed = failed.find((item) => !lastFailures.current.has(item.id))
    lastFailures.current = new Set(failed.map((item) => item.id))
    if (newlyFailed && uploadList.current) {
      uploadList.current.showPopover()
      uploadList.current
        .querySelector(`[data-upload-id="${newlyFailed.id}"]`)
        ?.scrollIntoView({ block: 'nearest' })
    }
  }, [items])
  const languages = caps.data?.languages ?? ['en', 'zh', 'ja', 'es']
  function add(files: File[], from = { x: innerWidth / 2, y: innerHeight - 30 }) {
    if (!files.length) return
    queue.current?.add(
      files,
      caps.data?.formats ?? Object.keys(TYPES),
      caps.data?.limits.max_upload_bytes ?? 50 * 1024 * 1024,
      languages.includes(settings.lang) ? settings.lang : undefined,
    )
    setLine(null)
    const actor = lenny.current
    if (actor) {
      const destination = mouthCenter(actor)
      feeding.current++
      actor.classList.remove('sleep')
      setOpen(actor, 1)
      void Promise.all(
        files.slice(0, 8).map((file, i) => {
          const type = typeOf(extOf(file.name))
          const rejected =
            !(caps.data?.formats ?? Object.keys(TYPES)).includes(extOf(file.name)) ||
            !file.size ||
            file.size > (caps.data?.limits.max_upload_bytes ?? 50 * 1024 * 1024)
          return flyCard(type.tag, type.tc, file.name, from, destination, i, rejected)
        }),
      ).finally(() => {
        feeding.current--
        if (!actor.isConnected || feeding.current) return
        setOpen(actor, 0)
        mood(actor, 'gulp', 400)
        mood(actor, 'chew', 1000)
      })
    }
  }
  async function feedSamples() {
    try {
      const names = [
        'Q3 销售汇报.pptx',
        '業務委託契約書_2026.docx',
        'Lista_de_precios_2026.xlsx',
        'manual_de_usuario.pdf',
        'meeting-notes.txt',
      ]
      const current = queue.current
      const files = await Promise.all(
        names.map(async (name) => {
          const response = await fetch(`/samples/${encodeURIComponent(name)}`)
          if (!response.ok) throw new Error('Sample files are unavailable.')
          return new File([await response.blob()], name)
        }),
      )
      if (current && current === queue.current) add(files)
    } catch {
      setMessage('Sample files are unavailable. Please choose a document.')
    }
  }
  function dragEnd() {
    pointer.dragging = false
    setDragging(false)
    document.body.classList.remove('dragging')
    if (!feeding.current) setOpen(lenny.current, 0)
  }
  function select(target: string) {
    cheer(lenny.current)
    queue.current?.select(target)
    setMessage('')
    setLine(null)
  }
  async function action(job: Job, kind: 'cancel' | 'dismiss' | 'download' | 'retry') {
    try {
      if (kind === 'retry') {
        if (!queue.current?.retryJob(job.id))
          setMessage('Choose the original file to retry this translation.')
        return
      }
      if (kind === 'download') await downloadCurrent(jobFileUrl(job.id))
      else {
        const next = await unwrap(
          kind === 'cancel'
            ? api.POST('/v1/jobs/{job_id}/cancel', { params: { path: { job_id: job.id } } })
            : api.POST('/v1/jobs/{job_id}/dismiss', { params: { path: { job_id: job.id } } }),
        )
        setLocalJobs((prev) => new Map(prev).set(next.id, next))
        if (kind === 'dismiss') {
          await tossToHistory(document.querySelector(`[data-job-id="${job.id}"]`))
          setHidden((prev) => new Set(prev).add(job.id))
        }
      }
      refreshWork(qc)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'The action could not be completed.')
      refreshWork(qc)
    }
  }
  const ws: Workspace = {
    say: setLine,
    restoreSpeech: () => setLine(null),
    toast: setMessage,
    pickFiles: () => picker.current?.click(),
    feedSamples: () => void feedSamples(),
    openHistory: () => setHistory(true),
    openSettings: () => setPreferences(true),
    signOut: onSignOut,
    startOver: () => {
      for (const i of items) if (!i.target) queue.current?.dismiss(i.id)
    },
    addBubble: (j) => setLocalJobs((p) => new Map(p).set(j.id, j)),
    onMeadow: (id) => jobs.has(id),
    forgetDocument: (id) =>
      setLocalJobs((p) => new Map([...p].filter(([, j]) => j.document_id !== id))),
  }
  function askToWait() {
    if (patienceTimer.current) clearTimeout(patienceTimer.current)
    lenny.current?.classList.remove('happy', 'sleep')
    lenny.current?.classList.add('annoyed')
    setImpatient(true)
    patienceTimer.current = setTimeout(() => {
      setImpatient(false)
      lenny.current?.classList.remove('annoyed')
    }, 3500)
  }
  const speech: Line = impatient
    ? {
        say: "Hey! I'm still working on that. Please wait!",
        sub: 'When its ring turns green, click the bubble to download.',
      }
    : (line ?? {
        say: dragging
          ? 'Ooh, is that for me? Drop it in!'
          : draft.length
            ? 'Om nom! What language shall I translate into?'
            : staged.length
              ? staged.every((item) => item.state === 'failed')
                ? 'Some files need attention. Check my tummy.'
                : 'Om nom! Getting your files ready to translate.'
              : visible.length
                ? visible.some((job) => !isTerminal(job))
                  ? 'Ptoo! Your translations are on their way.'
                  : visible.every((job) => job.status === 'succeeded' && job.result_available)
                    ? 'All done! Click a bubble to download.'
                    : 'Your batch has finished. Check each bubble for its result.'
                : `Hi ${me.display_name}! Drop your documents on me.`,
        sub: draft.length
          ? "Pick a language. I'll start as each file is ready."
          : staged.length
            ? staged.every((item) => item.state === 'failed')
              ? 'Open my tummy to retry or remove the affected files.'
              : `Target: ${[...new Set(staged.map((item) => languageName(item.target)))].join(', ')}. I'll start as each file is ready.`
            : 'I eat PowerPoint, Word, Excel, PDF and text. Drop more files any time.',
        extra: (
          <>
            {!draft.length ? (
              <div className="row-actions">
                <button className="btn alt" onClick={() => picker.current?.click()}>
                  Pick files
                </button>
                <button className="btn alt" onClick={() => setHistory(true)}>
                  History
                </button>
                {!draft.length && !visible.length ? (
                  <button className="btn alt" onClick={() => void feedSamples()}>
                    Feed me sample files
                  </button>
                ) : null}
              </div>
            ) : null}
            {draft.some((i) => i.retryable !== false) ? (
              <div className="chips" role="group" aria-label="Translate into">
                {languages.map((lang) => (
                  <button
                    className="chip translate-action"
                    key={lang}
                    aria-label={`Translate to ${languageName(lang)}`}
                    onClick={() => select(lang)}
                  >
                    {languageName(lang)}
                  </button>
                ))}
              </div>
            ) : null}
          </>
        ),
      })
  return (
    <WorkspaceContext.Provider value={ws}>
      <Header me={me} />
      <main
        id="stage"
        className="unified-stage"
        onDragOver={(e) => {
          if (!e.dataTransfer.types.includes('Files')) return
          e.preventDefault()
          e.dataTransfer.dropEffect = 'copy'
          pointer.dragging = true
          track(e.clientX, e.clientY)
          setDragging(true)
          document.body.classList.add('dragging')
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) dragEnd()
        }}
        onDrop={(e) => {
          e.preventDefault()
          dragEnd()
          add([...e.dataTransfer.files], { x: e.clientX, y: e.clientY })
        }}
      >
        <div className={`lenny-wrap${arriving ? ' arriving' : ''}`} id="lennyWrap">
          <Speech id="speech" who={lenny} line={speech} live={false} />
          <button
            id="lennyBtn"
            ref={button}
            aria-label="Lenny"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => {
              boop(lenny.current)
              setMenuOpen((open) => !open)
            }}
          >
            <Lenny ref={lenny} size="big" />
          </button>
          {staged.length ? (
            <button
              id="tummy"
              popoverTarget="tummy-files"
              aria-label={`View ${staged.length} files in Lenny's tummy`}
            >
              {staged.length} in my tummy <span aria-hidden="true">⌄</span>
              {staged.some((item) => item.state === 'failed') ? (
                <span className="tummy-error">Needs attention</span>
              ) : null}
            </button>
          ) : null}
        </div>
        {staged.length ? (
          <section
            className="tummy-files"
            id="tummy-files"
            ref={uploadList}
            popover="auto"
            aria-label="Uploads"
          >
            <div className="tummy-heading">
              <h2>
                In my tummy{' '}
                <small>
                  {staged.length} {staged.length === 1 ? 'file' : 'files'}
                </small>
              </h2>
              <button
                className="icon-btn"
                popoverTarget="tummy-files"
                popoverTargetAction="hide"
                aria-label="Close file list"
              >
                ×
              </button>
            </div>
            <ul>
              {staged.map((item) => (
                <li
                  key={item.id}
                  data-upload-id={item.id}
                  className={item.state === 'failed' ? 'upload-failed' : undefined}
                >
                  <FileIcon format={extOf(item.file.name)} />
                  <b>{item.file.name}</b>
                  <span role={item.state === 'failed' ? 'alert' : undefined}>
                    {item.target ? `To ${languageName(item.target)} · ` : ''}
                    {item.state === 'uploading'
                      ? `Uploading ${Math.floor((item.sent / Math.max(1, item.total)) * 100)}%`
                      : item.state === 'ready'
                        ? 'Ready'
                        : item.state === 'submitting'
                          ? 'Submitting'
                          : item.state === 'failed'
                            ? `Failed: ${item.error}`
                            : 'Waiting to upload'}
                  </span>
                  {item.doc ? (
                    <small>
                      Detected:{' '}
                      {item.doc.detection === 'mixed'
                        ? 'Mixed'
                        : item.doc.detected_source
                          ? languageName(item.doc.detected_source)
                          : 'Unknown'}
                    </small>
                  ) : null}
                  <div className="row-actions">
                    {item.state === 'failed' ? (
                      <>
                        <button
                          className="btn alt"
                          disabled={item.retryable === false}
                          aria-label={`Retry ${item.file.name}`}
                          onClick={() => queue.current?.retry(item.id)}
                        >
                          Retry
                        </button>
                        <button
                          className="btn alt"
                          aria-label={`Remove ${item.file.name}`}
                          onClick={() => queue.current?.dismiss(item.id)}
                        >
                          Remove
                        </button>
                      </>
                    ) : (
                      <button
                        className="btn alt"
                        aria-label={`Cancel ${item.file.name}`}
                        onClick={() => queue.current?.cancel(item.id)}
                      >
                        Cancel
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
        <Bubbles
          jobs={visible}
          fresh={fresh}
          onWait={askToWait}
          onAction={(job, kind) => void action(job, kind)}
        />
        {!visible.length && !staged.length ? (
          <p className="drop-hint">Drop files anywhere in this meadow, or choose Pick files.</p>
        ) : null}
      </main>
      <LennyMenu
        open={menuOpen}
        anchor={button}
        head="What's cooking?"
        sub="Drop your files and I'll take a bite."
        onClose={(focus) => {
          setMenuOpen(false)
          if (focus) button.current?.focus()
        }}
        onSettings={() => {
          setMenuOpen(false)
          setPreferences(true)
        }}
        items={[
          { act: 'pick', icon: 'upload', label: 'Pick files', run: () => picker.current?.click() },
          {
            act: 'samples',
            icon: 'sparkles',
            label: 'Feed me sample files',
            run: () => void feedSamples(),
          },
          { act: 'history', icon: 'history', label: 'History', run: () => setHistory(true) },
          { act: 'restart', icon: 'rotate', label: 'Start over', run: ws.startOver },
        ]}
      />
      <input
        id="picker"
        hidden
        type="file"
        multiple
        ref={picker}
        aria-label="Choose documents to translate"
        accept={Object.keys(TYPES)
          .map((f) => `.${f}`)
          .join(',')}
        onChange={(e) => {
          add([...(e.target.files ?? [])])
          e.target.value = ''
        }}
      />
      {history ? <History onClose={() => setHistory(false)} /> : null}
      {preferences ? (
        <SettingsSheet languages={languages} onClose={() => setPreferences(false)} />
      ) : null}
      <div className="sr-only" role="status" aria-live="polite">
        {impatient
          ? 'Lenny is still working. Please wait until the ring turns green, then click the bubble to download. '
          : ''}
        {`${message} ${visible.filter((j) => j.status === 'succeeded' && j.result_available).length} ready to download. ${visible.filter((j) => !isTerminal(j)).length} translating. ${[
          ...new Set(
            visible
              .filter((j) => !isTerminal(j))
              .map((j) => j.fallback)
              .filter(Boolean),
          ),
        ].join('. ')}`}
      </div>
      {message ? (
        <div id="toast">
          <span>{message}</span>
          <button
            className="btn alt"
            aria-label="Dismiss notification"
            onClick={() => setMessage('')}
          >
            Close
          </button>
        </div>
      ) : null}
      {caps.isError ? (
        <p className="svc-down" role="alert">
          The service is unavailable. Try again shortly.
        </p>
      ) : null}
    </WorkspaceContext.Provider>
  )
}
