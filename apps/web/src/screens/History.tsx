import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { downloadCurrent, websiteRequest } from '../api/client'
import { languageName, whenLabel, extOf } from '../lib/format'
import { FileIcon } from '../ui/FileIcon'
import { Icon } from '../ui/icons'
import { useDialog } from '../ui/useDialog'
interface Entry {
  id: string
  original_name: string
  source: string | null
  target: string
  status: string
  created_at: string
  updated_at: string
  available: boolean
}
interface Page {
  items: Entry[]
  next_cursor: string | null
}
export function History({ onClose }: { onClose: () => void }) {
  const sheet = useRef<HTMLElement>(null)
  useDialog(sheet, onClose)
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<string | null>(null)
  const query = useInfiniteQuery({
    queryKey: ['history'],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      websiteRequest<Page>(
        `/v1/history?limit=50${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ''}`,
      ),
    getNextPageParam: (p) => p.next_cursor,
    refetchInterval: 10000,
  })
  async function act(item: Entry, kind: 'download' | 'delete') {
    setBusy(item.id)
    setError('')
    try {
      if (kind === 'download')
        await downloadCurrent(`/v1/history/${encodeURIComponent(item.id)}/file`)
      else await websiteRequest(`/v1/history/${encodeURIComponent(item.id)}`, 'DELETE')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The action failed.')
    } finally {
      setBusy(null)
      setConfirm(null)
      void qc.invalidateQueries({ queryKey: ['history'] })
      void qc.invalidateQueries({ queryKey: ['jobs'] })
    }
  }
  return (
    <div
      id="history"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <section
        className="sheet history-sheet"
        ref={sheet}
        role="dialog"
        aria-modal="true"
        aria-labelledby="history-title"
      >
        <div className="sheet-head">
          <h2 id="history-title">History</h2>
          <p>
            Your filenames and language pairs are private. Download retrieves the currently
            available translation.
          </p>
          <button
            className="icon-btn"
            aria-label="Close History"
            title="Close History"
            onClick={onClose}
          >
            <Icon name="x" />
          </button>
        </div>
        <div className="sheet-body">
          {error || query.isError ? (
            <p role="alert">
              {error || 'History could not be loaded.'}
              <button className="btn alt" onClick={() => void query.refetch()}>
                Refresh
              </button>
            </p>
          ) : null}
          {query.isPending ? <p>Loading History...</p> : null}
          {query.data?.pages.flatMap((p) => p.items).length === 0 ? (
            <p>No translations yet.</p>
          ) : null}
          <div className="history-columns" aria-hidden="true">
            <span>Document</span>
            <span>Languages</span>
            <span>Status</span>
            <span>Updated</span>
            <span>Actions</span>
          </div>
          <ul className="history-entries">
            {query.data?.pages
              .flatMap((p) => p.items)
              .map((item) => (
                <li
                  key={item.id}
                  aria-labelledby={`history-name-${item.id}`}
                  aria-busy={busy === item.id}
                >
                  <FileIcon format={extOf(item.original_name)} />
                  <h3 id={`history-name-${item.id}`} title={item.original_name}>
                    {item.original_name}
                  </h3>
                  <div className="history-meta">
                    <span className="history-language">
                      {languageName(item.source)} → {languageName(item.target)}
                    </span>
                    <span
                      className={`history-state${item.available ? ' available' : ''}`}
                      title={
                        !item.available && item.status === 'succeeded'
                          ? 'Upload the original to translate it again.'
                          : undefined
                      }
                    >
                      {item.available
                        ? 'Ready'
                        : item.status === 'succeeded'
                          ? 'Unavailable'
                          : item.status === 'running'
                            ? 'Translating'
                            : item.status === 'queued'
                              ? 'Queued'
                              : item.status === 'failed'
                                ? 'Failed'
                                : item.status === 'cancelled'
                                  ? 'Cancelled'
                                  : item.status}
                    </span>
                    <time
                      dateTime={item.updated_at || item.created_at}
                      title={new Date(item.updated_at || item.created_at).toLocaleString()}
                    >
                      {whenLabel(item.updated_at || item.created_at)}
                    </time>
                  </div>
                  <div className="history-actions">
                    <button
                      className="icon-btn"
                      aria-label={`Download ${item.original_name}`}
                      title={
                        item.available
                          ? `Download ${item.original_name}`
                          : 'Translation unavailable. Upload the original to translate it again.'
                      }
                      disabled={busy === item.id || !item.available}
                      onClick={() => void act(item, 'download')}
                    >
                      <Icon name="download" />
                    </button>
                    <button
                      className="icon-btn"
                      aria-label="Remove from History"
                      title={`Remove ${item.original_name} from History`}
                      disabled={busy === item.id}
                      onClick={() => setConfirm(confirm === item.id ? null : item.id)}
                    >
                      <Icon name="trash" />
                    </button>
                  </div>
                  {confirm === item.id ? (
                    <div
                      className="history-confirm"
                      role="group"
                      aria-label={`Remove ${item.original_name}`}
                    >
                      <p>
                        Remove this entry and your access to its translation? Other users are
                        unaffected.
                      </p>
                      <button
                        className="btn alt"
                        disabled={busy === item.id}
                        onClick={() => void act(item, 'delete')}
                      >
                        Remove entry
                      </button>
                      <button className="btn alt" onClick={() => setConfirm(null)}>
                        Keep entry
                      </button>
                    </div>
                  ) : null}
                </li>
              ))}
          </ul>
          {query.hasNextPage ? (
            <button
              className="btn alt"
              disabled={query.isFetchingNextPage}
              onClick={() => void query.fetchNextPage()}
            >
              Load more
            </button>
          ) : null}
        </div>
      </section>
    </div>
  )
}
