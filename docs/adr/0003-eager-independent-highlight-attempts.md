# Start highlight attempts at assessment completion and claim each one independently

Amends ADR 0002. Durable execution stays: Cloud Tasks delivery, Scheduler
recovery of persisted dispatch intent, Firestore leases, private GCS masks,
retryable deletion and the independent local worker. What changes is when work
starts and how it is claimed.

The initial assessment response names one short SAM concept per finding. The same
Firestore commit that saves the findings also saves one initial attempt per finding
(queued, or unavailable with a reason) and the dispatch intent, so a crash between
analysis and enqueue cannot lose work. Enqueue happens after that commit; failure
is recovered from the persisted intent. Opening a finding only reads saved state.

Each attempt is its own task and its own claim. ADR 0002's per-assessment queue,
which let only one attempt per assessment run, is removed: a slow or failed finding
no longer blocks its siblings. Claims still prevent a started attempt from running
twice, and retry creation still refuses while an attempt for the same revision is
active. Shared writes keep update-time compare-and-set preconditions; a conflict
re-reads the document and reapplies the pure change, so sibling progress is never
overwritten and no provider call is repeated to resolve contention.

Each attempt makes one SAM request and no main-model calls. The highest-confidence
valid candidate is published without model review, a deliberate latency tradeoff:
it can mark the wrong instance, and the app labels it as AI-generated. Capacity
admits 12 overlapping attempts (the finding limit): Cloud Run concurrency 8 with 2
instances, a queue allowing 24 concurrent dispatches, a 12-thread local worker, and
at most 4 mask-decoding processes per instance.
