# Run finding chat replies as durable streaming jobs

Finding chat replies were generated synchronously inside the client's HTTP
request and saved only when complete. Replies now run as durable jobs that reuse
the highlight infrastructure (ADRs 0002 and 0003): accepting a question saves it,
a queued attempt and dispatch intent in one Firestore commit; Cloud Tasks delivers
`/internal/chat/work` with service OIDC on the existing queue; the Scheduler sweep
and the local worker re-deliver queued attempts and fail expired ones. A started
stream is never restarted, and only an explicit Retry creates a new attempt.

Providers stream plain answer text (Groq cannot stream Structured Outputs). The
worker persists the accumulated partial text at most every 0.75 seconds with a
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
