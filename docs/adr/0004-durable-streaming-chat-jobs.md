# Run finding chat replies as durable streaming jobs

Finding chat replies were generated synchronously inside the client's HTTP
request and saved only when complete. Replies now run as durable jobs that reuse
the highlight infrastructure (ADRs 0002 and 0003): accepting a question saves it,
a queued attempt and dispatch intent in one Firestore commit; Cloud Tasks delivers
`/internal/chat/work` with service OIDC on the existing queue; the Scheduler sweep
and the local worker re-deliver queued attempts and fail expired ones. A started
stream is never restarted, and only an explicit Retry creates a new attempt.

Providers stream plain answer text (Groq cannot stream Structured Outputs). The
worker persists the accumulated partial text at most every 0.2 seconds with a
monotonic version, inside the existing assessment document and through the same
transactional read-modify-write. This keeps execution, ownership and deletion
fences atomic with concurrent status, sibling chat and highlight updates, and
lets existing retryable deletion remove job state. The tradeoff is rewriting the
bounded assessment document on each batch rather than per token; the document size
guard and per-turn limits bound the cost. A separate chunk log or collection was
rejected because it would need its own fences, deletion and retention.

Deadlines fit Cloud Run's 300-second request limit: 600 s queue, 180 s stream
budget, 210 s execution lease, 240 s task dispatch deadline. Clients observe
progress by short authenticated polling, which never starts work.

## Amendment (2026-11-01): faster delivery, polling retained

Users saw answers appear only near completion. Two causes: partial writes ran
inline only when the next fragment arrived (text before a provider pause waited
for a later fragment), and 0.75 s batching plus 1 s polling after each response
put delivery well beyond the 500 ms provider-to-screen target. A background
publisher now flushes the latest text at most every 0.2 s, including during
provider pauses, without blocking provider reads; clients poll an active job
every 250 ms on a fixed cadence. Connected web measurement (local API and
Firestore emulator, loopback) observed a median of 132 ms and a maximum of 232 ms.

Polling is kept over client SSE/WebSocket: it reuses the authenticated read,
ownership and recovery rules, and remains correct across reconnects and app
backgrounding. Load per active reply rises to at most 5 document rewrites and
about 4 reads per viewing client per second, only while a reply streams
(normally seconds, bounded by the 180 s stream budget). This exceeds Firestore's
soft 1 write/s sustained-per-document guidance in short bursts; contention is
absorbed by transactional retries and the bounded duration. Revisit with a
streaming transport if many viewers or longer answers make this load material.
