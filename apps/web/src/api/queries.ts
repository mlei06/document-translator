// Server state through TanStack Query: one polling coordinator for visible work (progress plan),
// the ADR-014 library, identity and capabilities. Mutations refetch so a stale poll never undoes
// a confirmed change.
import {
  keepPreviousData,
  useInfiniteQuery,
  useQuery,
  useQueryClient,
  type Query,
  type QueryClient,
} from '@tanstack/react-query'
import { api, ApiError, unwrap, type Doc, type Job } from './client'
import { isTerminal } from '../lib/format'

export const keys = {
  me: ['me'] as const,
  capabilities: ['capabilities'] as const,
  activeJobs: ['jobs', 'active'] as const,
  job: (id: string) => ['jobs', 'one', id] as const,
  documents: (q: string) => ['documents', q] as const,
  document: (id: string) => ['documents', 'one', id] as const,
  preview: (kind: string, id: string) => ['preview', kind, id] as const,
  report: (kind: string, id: string) => ['report', kind, id] as const,
}

/** Poll about every 2 s while work is unfinished; back off to 5/10/30 s after failures. */
function pollDelay(failures: number, busy: boolean): number | false {
  if (failures > 0) return [5000, 10000, 30000][Math.min(failures - 1, 2)]!
  return busy ? 2000 : false
}

export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: () => unwrap(api.GET('/v1/me')),
    staleTime: 30_000,
  })
}

export function useCapabilities() {
  return useQuery({
    queryKey: keys.capabilities,
    queryFn: ({ signal }) => unwrap(api.GET('/v1/capabilities', { signal })),
    staleTime: 60_000,
    refetchInterval: 60_000,
  })
}

/** Follow every bounded page: newer completed jobs must not hide older live work. */
export async function fetchActiveJobs(signal?: AbortSignal): Promise<Job[]> {
  const jobs = new Map<string, Job>()
  let cursor: string | undefined
  do {
    const page = await unwrap(
      api.GET('/v1/jobs', {
        params: { query: { active: true, limit: 200, cursor } },
        signal,
      }),
    )
    for (const job of page.items) jobs.set(job.id, job)
    cursor = page.next_cursor ?? undefined
  } while (cursor)
  return [...jobs.values()]
}

/** Unfinished jobs plus finished ones not yet opened, downloaded or cleared (ADR-017). */
export function useActiveJobs(extraBusy: boolean, poll = true) {
  return useQuery({
    queryKey: keys.activeJobs,
    queryFn: ({ signal }) => fetchActiveJobs(signal),
    refetchInterval: (query: Query<Job[], Error>) =>
      poll &&
      pollDelay(
        query.state.fetchFailureCount,
        extraBusy || (query.state.data ?? []).some((j) => !isTerminal(j)),
      ),
    retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
  })
}

/** One saved document (its upload-time detection), fetched only when a caller needs it. */
export function useDocument(id: string | null) {
  return useQuery({
    queryKey: keys.document(id ?? ''),
    enabled: id !== null,
    queryFn: () =>
      unwrap(api.GET('/v1/documents/{document_id}', { params: { path: { document_id: id! } } })),
    staleTime: 60_000,
    retry: false,
  })
}

/** One job, polled while unfinished (used for jobs that left the active list). */
export function useJob(id: string | null) {
  return useQuery({
    queryKey: keys.job(id ?? ''),
    enabled: id !== null,
    queryFn: () => unwrap(api.GET('/v1/jobs/{job_id}', { params: { path: { job_id: id! } } })),
    refetchInterval: (query: Query<Job, Error>) =>
      pollDelay(
        query.state.fetchFailureCount,
        query.state.data ? !isTerminal(query.state.data) : false,
      ),
  })
}

export function useDocuments(q: string, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: keys.documents(q),
    enabled,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET('/v1/documents', {
          params: { query: { q: q || undefined, cursor: pageParam ?? undefined, limit: 50 } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? null,
    placeholderData: keepPreviousData,
    refetchInterval: (query) => {
      const docs: Doc[] = query.state.data?.pages.flatMap((p) => p.items) ?? []
      return pollDelay(
        query.state.fetchFailureCount,
        docs.some((d) => Object.keys(d.active_jobs).length > 0),
      )
    },
  })
}

/** After a change: refresh everything that could show it. */
export function refreshWork(qc: QueryClient): void {
  void qc.invalidateQueries({ queryKey: ['jobs'] })
  void qc.invalidateQueries({ queryKey: ['documents'] })
  void qc.invalidateQueries({ queryKey: keys.me })
}

export function useRefreshWork(): () => void {
  const qc = useQueryClient()
  return () => refreshWork(qc)
}

export interface ResultReport {
  diagnostics?: { code: string; count: number }[]
}
