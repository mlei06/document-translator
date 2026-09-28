# ADR-008: Job Execution Model

## Status

Accepted (2026-09-27)

## Context

The server runs translations as asynchronous jobs ([ADR-001](ADR-001-mcp-server-deployment.md), [ADR-004](ADR-004-job-storage.md)). This ADR decides where jobs execute relative to the web process, how work is handed to them, and how failures are recovered. It resolves the job execution model deliverable of P5.

Forces:

- **Jobs are long and heavy.** Seconds to minutes each. MT mode is CPU-bound inference; rendering (P7) runs LibreOffice. Both can use a lot of memory, and LibreOffice can hang.
- **The API must stay responsive.** Web users and agents poll job status while translations run.
- **Job state is persistent and shared.** ADR-001 rule 2 requires that nothing is lost when a connection drops or a process restarts; job state lives in the database. REST, MCP, and the web GUI read the same state.
- **Hosting.** One laptop now, with no one to operate extra services (ADR-004). Later a shared server or company-controlled cloud, where translation capacity should scale independently of the web process.
- **Volume.** Tens of jobs per minute at most, each dominated by translation time.
- **Portability.** ADR-004 rule 4: no SQLite-specific SQL; moving to PostgreSQL is a connection URL change.

## Options Considered

### A. In-process execution (thread pool or FastAPI background tasks in the web process)

Pros:
- One process; nothing to coordinate.

Cons:
- CPU-heavy MT inference and rendering compete with request handling in the same process.
- An out-of-memory error or native crash takes down the API and MCP endpoint with it.
- Restarting the web process kills running translations.
- Scaling translation means scaling the web process.

### B. Separate worker processes, using the jobs table as the queue

Pros:
- Web process never runs translation; a crashing worker affects only its current job.
- The queue is the job state itself: one source of truth, no dual writes.
- No additional service to run. Works on SQLite on one host and on PostgreSQL across hosts.
- Scaling is running more workers.

Cons:
- Workers poll the database for work (about once a second when idle).
- Leases, retries, and requeueing are implemented in the server rather than taken from a library.

### C. Task queue library with a broker (Celery, RQ, Dramatiq with Redis or RabbitMQ)

Pros:
- Mature retry and worker management.

Cons:
- Requires running a broker. Redis keeps state in memory and is not durable by default.
- Job state is kept twice (broker and database), so submission must write both atomically, which needs an outbox table and relay.
- Celery does not officially support Windows, the laptop's OS.

### D. RabbitMQ (or a managed broker such as Azure Service Bus) as the queue, with database job state

Pros:
- Durable messages, acknowledgements, redelivery, routing to many consumers.

Cons:
- The same dual-write problem as C.
- An Erlang service to install and operate on the laptop.
- Consumers holding a message unacknowledged longer than the delivery acknowledgement timeout (30 minutes by default) have their channel closed, which long jobs must be configured around.
- Progress and cancellation still go through the database.
- Its strengths (high message rates, fan-out to many consumers, cross-system events) are not needs of this system.

## Decision

Option B: separate worker processes, with the `jobs` table as the queue. No broker.

### Processes

- The `doctranslator-server` command has two subcommands: `serve` (FastAPI: REST, MCP, web GUI; never runs the pipeline) and `worker` (claims and runs jobs; does not import FastAPI).
- On the laptop, `serve --workers N` also starts N worker child processes and restarts a crashed worker after a backoff, so one command runs everything. On a shared or cloud host, `serve` and `worker` run as separate services and workers are scaled independently.
- Each worker keeps its `Translator` instances alive between jobs, one per engine configuration, so an MT model loads once per worker. The worker count is bounded by host memory and cores; the laptop default is set in the P5 plan.

### Job record

The `jobs` table carries, in addition to job metadata: `kind` (`translate` now; `edit` and `render` in P7), `status` (`queued`, `running`, `succeeded`, `failed`, `cancelled`), `attempts`, `max_attempts`, `available_at`, `worker_id`, `lease_until`, `cancel_requested`, `phase`, `progress_done`, `progress_total`, `error_code`, `error_message`, `cache_hit`, and timestamps. It is indexed for claiming on `(status, available_at, created_at)`.

### Rules

1. **The database is the only record of jobs.** Anything that wakes workers (polling today) carries at most a job ID and is never authoritative.
2. **Submission never waits for a worker.** The API writes the job (and, on a cache hit, its completed result, per [ADR-007](ADR-007-translation-reuse-and-document-storage.md)) in one transaction and returns.
3. **Claiming is one conditional update.** A worker sets `status = running`, its `worker_id`, a lease, and increments `attempts` on the oldest `queued` job whose `available_at` has passed, conditioned on the job still being `queued`. It owns the job only if the update changed a row. Written with SQLAlchemy constructs only; on PostgreSQL, `FOR UPDATE SKIP LOCKED` may be added as an optimization.
4. **Leases.** A running worker extends its lease on a heartbeat (e.g. every 30 s for a 2-minute lease) and checks `cancel_requested` at the same time. A heartbeat that updates no row means the worker has lost the job; it abandons the job without writing results.
5. **Fenced completion.** A worker commits its result (result rows, document version, `status = succeeded`) in one transaction conditioned on `worker_id` still being its own. A worker that lost its lease cannot overwrite the job. Output files are content-addressed blobs, so a duplicate write is harmless and unreferenced blobs are removed by retention.
6. **Recovery.** Running jobs whose lease has expired are returned to `queued` if attempts remain, otherwise marked `failed` with a "worker crashed repeatedly" reason. Any worker performs this sweep before claiming. Because attempts are counted at claim time, a document that crashes workers fails after `max_attempts` instead of looping.
7. **Error classes.** Transient errors (`EngineUnavailableError`, server-side errors after the engine's own retries) requeue the job with `available_at` pushed back by a growing backoff. Permanent errors (`EngineAuthenticationError`, a corrupt or unsupported document, invalid options) fail the job immediately with a clear `error_code` and message.
8. **Progress and cancellation.** The worker passes a progress callback to the core pipeline. Between batches, the callback writes `phase` and progress (throttled to about once a second) and raises a cancellation exception if cancellation was requested. Cancelling a queued job marks it `cancelled` at once; a running job stops at the next batch boundary.
9. **Cache re-check.** Immediately before translating, the worker looks up the document cache again (ADR-007), so identical submissions queued together are usually translated once without any lock.
10. **Edits are jobs.** Edit and render jobs use the same queue. An edit job commits a new document version only if its base version is still the latest; otherwise it fails with a conflict the client can retry.
11. **Time.** On one host, leases use the host clock. When workers run on several hosts (PostgreSQL), lease times come from the database's clock.
12. **Shutdown.** On a stop signal a worker stops claiming, and finishes or abandons its current job. An abandoned job is recovered by lease expiry (rule 6).

### Code location

- `jobs/queue.py`: submit, claim, heartbeat, complete, fail, requeue, cancel. Queries go through `db/repositories/`.
- `jobs/worker.py`: the worker loop, `Translator` reuse, error classification, progress callback.
- `jobs/notifier.py`: the wakeup interface (`notify(job_id)`, `wait(timeout)`), implemented by polling.
- `cli.py`: the `serve` and `worker` subcommands. It builds settings and delegates to `app` and `jobs`; it does not import `db`.

`jobs` remains the only server module that calls the core pipeline ([ADR-003](ADR-003-source-structure.md) rule 4).

## Consequences

- The web process stays responsive regardless of translation load, and a crashing translation never takes the API or MCP endpoint down.
- Several processes share one SQLite file on one host. WAL mode (ADR-004 rule 3) lets readers proceed during writes; connections also set a busy timeout so a writer waits briefly for the lock instead of failing. Writes are small (status, progress, leases). Workers on more than one host require PostgreSQL and shared blob storage.
- The core pipeline's public API gains an optional progress callback (P2) that can abort the run by raising. It is a plain callable, so the core stays free of server concerns.
- Idle workers add about one small query per second each.
- The server owns lease, retry, and recovery logic, tested with a fake pipeline, temporary SQLite databases, and an injectable clock, plus one end-to-end test that kills a worker process mid-job and checks that another worker completes it.
- Revisit a broker (option D, or a managed equivalent such as Azure Service Bus) when one of these holds: other systems need to consume job events; the job rate makes polling a measurable database load; or workers must run without database access. Rule 1 keeps that change to a new `notifier` implementation, with claim, lease, and completion logic unchanged.
- ADR-001 is unaffected: the MCP endpoint remains in the web process, and only execution moves to workers.
