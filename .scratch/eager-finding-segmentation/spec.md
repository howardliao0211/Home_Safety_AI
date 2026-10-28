# Start finding segmentation immediately after assessment

Date: 2026-10-28

## Problem and intended outcome

Highlights currently start when a finding is opened. Each attempt calls the main
model to select an object and bounding box, calls SAM to segment it, then calls
the main model again to review the candidates. Jobs within an assessment run
serially. This makes users wait after selecting each finding.

After this change, the original assessment response includes a short segmentation
prompt for each initial finding. Completing the assessment automatically queues
independent SAM 3.1 jobs for all eligible initial findings. Jobs run concurrently,
and the app fetches saved progress/results. Opening a finding does not initiate
model work. Remove both extra main-model calls and remove photo zoom.

This spec changes the existing behavior described in
`../hazard-highlighting/spec.md`; it takes precedence for the behavior below.
This deliverable is a specification, not an implementation.

## Decisions confirmed in the discussion

- Remove the zoom option and fullscreen photo viewer; retain inline evidence.
- Automatically segment initial findings only. Successful follow-up or
  user-requested review analysis does not automatically generate another highlight.
- Backend jobs continue after navigation, app closure, or client disconnection.
- The main model identifies what to segment in the original assessment call.
  SAM supplies the bounding box and mask; the main model need not supply a box.
- Remove separate main-model selection and post-segmentation localisation review.
  User-requested safety reviews remain part of the assessment workflow.
- Publish one valid mask per finding, preferring the highest provider confidence;
  use provider order if scores are absent. Retain incorrect-object feedback.
- Localisation quality is a deliberate tradeoff for latency. A future decision
  may restore model review; it is outside this change.

## Provider capability verified

Meta documents that SAM 3.1 accepts an image and a short noun phrase and produces
boxes and masks for matching instances. A bounding-box input is optional. This
supports the intended split: the assessment model names the object, then SAM
localises it. Use concrete attributes rather than hazard explanations or commands.
Text prompts can return several instances; positional wording is unreliable.
[Meta: Segmenting with prompts](https://dev.meta.ai/docs/sam/segmenting).

Request per-object scores with `metadata.include_confidence: "true"`, and retain
the existing compact mask encoding. A score ranks detections; it does not prove
that a particular instance is the one intended by the finding. No live inference
or account-access verification was performed while preparing this spec.
[Meta: Request confidence](https://dev.meta.ai/docs/sam/segmenting#request-confidence).

Continue using the dedicated parser for SAM geometry and mask output. Empty
completed output represents no match, rather than a provider failure.
[Meta: Reading segmentation output](https://dev.meta.ai/docs/sam/reading-segmentation),
[official SAM protocol](https://github.com/meta-models/meta-sam/blob/main/protocol/sam3.md).

## Assessment output and scheduling

Extend the initial finding model output with a nullable `segmentation_prompt`.
It names one main visible object that supports the finding, preferably the object
the recommended action concerns. For example, a recommendation to move curtains
away from a heater should target `curtains`. Include visible color or type where
useful to distinguish similar objects. Do not request coordinates, multiple
concepts, negative instructions, or a reasoning paragraph in this field.

Use null when no suitable visible object exists. Validate and normalize this
optional field independently of the safety content. A missing, blank, invalid,
or excessively long prompt leaves the finding usable without a highlight and
does not trigger another main-model call. Bound the stored prompt to 200
characters. Persist an annotation-specific unavailable reason where appropriate.

The prompt is internal localisation metadata, separate from the user-facing
finding content. Bind it to the initial finding-content revision and the initial
assessment photo. Do not let SAM select a different evidence photo.

When initial safety analysis succeeds, save the findings, prompt metadata, initial
annotation attempts, and durable dispatch intent in the same authoritative commit.
This prevents a crash between assessment completion and job creation from losing
automatic work. The successful response includes lightweight annotation metadata
and attempt IDs, without waiting for SAM or mask storage. A dispatch outage leaves
recoverable queued work and does not invalidate the completed assessment.

Create exactly one initial attempt per eligible finding. Null prompts, unsupported
provider configuration, and assessments with no findings produce no SAM calls.
An assessment retry must not duplicate jobs for already committed findings.
Highlight failure cannot change an assessment's safety-analysis outcome.

## Segmentation and candidate selection

Each attempt sends one concept prompt and the original, correctly oriented photo
to `sam-3.1` through the configured `MUSE_SEGMENTATION_MODEL` adapter. Validate that
the deployed model supports this contract. Reuse backend-only credentials and
stream handling. One attempt makes at most one SAM request. Do not combine all
findings into one multi-concept request or make follow-up selection/review calls.

Retain confidence when decoding candidates. Validate source dimensions,
orientation, frame identity, unique object IDs, mask decoding, nonempty masks,
and finite in-bounds geometry before a candidate can be published. Keep explicit
response-size and decode-resource bounds. Existing candidate-count limits must
not cause silent truncation before ranking; if output exceeds a supported bound,
fail that attempt explicitly rather than claiming the best overall candidate.

Choose one candidate using this deterministic policy:

1. Exclude candidates that fail independent geometry/mask validation. A malformed
   response or untrustworthy source geometry fails the attempt as a whole.
2. Among valid candidates with a finite confidence in `[0, 1]`, choose the highest
   confidence. Treat an invalid score as absent; scored candidates precede
   unscored candidates. Preserve provider order for equal scores.
3. If no valid candidate has a score, choose the first valid candidate in provider
   order. Do not interpret object IDs as confidence or sort by object ID.
4. Publish only that candidate's mask and box. Do not merge different instances.

No matching objects produces `unavailable`; provider, decoding, interruption,
or deadline failures produce `failed`. Preserve the existing manual retry flow
for eligible initial attempts, using the saved prompt and photo. No automatic
model retries or regeneration. Retry never calls the main model.

Unreviewed localisation can select the wrong repeated instance or contain mask
errors. Do not claim guaranteed instance correctness or semantic validation.
Local validation remains mandatory even though model review is removed.

## Concurrent durable execution

Keep Cloud Tasks delivery, persisted dispatch recovery, Firestore claims/leases,
private GCS masks, and an independent local worker. Client polling and request-local
background tasks must not own execution.

Remove the per-assessment active-job restriction. Queue and dispatch every eligible
finding independently as soon as the assessment commit succeeds. A slow, failed,
or timed-out finding must not block a sibling finding. Use concurrent asynchronous
provider I/O with separate attempt deadlines and resource-bounded mask decoding;
a separate operating-system process per HTTP call is not required.

The current assessment limit is 12 findings. Worker and dispatch configuration must
support overlapping work for those findings, without a product-level serial queue
within an assessment. Review Cloud Tasks concurrency, Cloud Run request concurrency,
instance limits, and local worker scheduling together; existing deployment settings
must not silently preserve serial behavior. Configure capacity to admit up to 12
concurrent attempts for one assessment, within global resource/provider limits.
Infrastructure queueing can still occur under load; exact simultaneous starts
and a fixed wall-clock latency are not guaranteed.

Claims deduplicate individual attempts and prevent simultaneous retries for the
same finding revision. Preserve the 30-second budget from claim to publication,
excluding queue wait. A duplicate delivery or recovery sweep must not restart a
provider call already started. Expired started work becomes a manually retryable
failure. Late results cannot publish after expiry.

Shared Firestore writes must tolerate sibling jobs progressing concurrently.
Preserve atomic claim/publication preconditions without lost sibling updates or
repeating provider calls to recover from storage contention. Preserve revision,
source digest, deletion, lease, and asset-cleanup protections.

## Fetching progress and mobile behavior

Render the assessment photo and findings as soon as safety analysis completes.
Keep the assessment overview photo unannotated. The backend starts work whether
or not any finding is selected.

Use annotation IDs/statuses in assessment reads to discover the initial jobs.
Opening a finding fetches its existing attempt and polls the existing status
endpoint every two seconds while queued/processing and the screen is active.
Reuse the existing endpoint shapes where possible; no mask bytes in assessment
responses. Do not POST a new annotation request merely on mounting, focus,
refresh, reconnection, or app restart.

Stop polling at terminal state or when the app/screen is inactive. On focus or
reconnection, fetch authoritative saved state immediately and resume polling only
if necessary. Polling failure does not create or retry a model attempt. Work
continues independently while the client is inactive. Keep polling requests from
overlapping for the same attempt.

Use the existing queued/processing/ready/unavailable/failed/reported states.
Keep findings interactive while highlighting is pending. A ready highlight shows
the inline source photo with an aligned overlay. Replace claims such as “Reviewed
object highlight” with “AI-generated highlight” in visible and accessibility text.
Retain readable evidence, Hide highlights, manual retry, and Incorrect object.
Incorrect-object feedback persistently hides the mask without changing finding
content or checklist status, and does not automatically regenerate it.

Remove Zoom photo, the fullscreen modal, Zoom in/out, Close photo, and zoom-specific
state/styles/accessibility controls. Keep the full inline image aspect ratio and
the shared photo/mask transform, including historical evidence rendering.

## Revisions, existing records, and lifecycle

Automatic generation applies only to initial findings from newly completed
assessments. Successful follow-up/review revisions do not start segmentation,
including when opened. An old revision's mask must not appear as the revised
finding's current highlight. Keep historical masks with their historical evidence.
A stale job cannot publish into the new current revision.

For this initial-findings scope, do not add an on-demand generation path for newer
revisions. Preserve status actions and user-requested safety reviews. Status-only
changes do not create a content revision or rerun segmentation.

Do not automatically backfill existing assessments or infer prompts from their
finding prose. Preserve saved attempts/results and historical evidence. A legacy
record without a saved prompt remains readable without generating new model work;
explain unavailable retry capability rather than restoring an extra selection call.

Keep device scoping, demo authorization, private mask access, retryable deletion,
orphan cleanup, retention limits, and diagnostic logging. Deletion cancels queued
work and fences all concurrent publishers. Logs may include stage timings and
identifiers, but never credentials or image/mask payloads.

## Documentation and architecture changes required during implementation

This proposal changes ADR 0002's per-assessment claim arrangement and the serial
behavior it supports. Record a superseding/amending decision for independent
attempt claims while preserving durable execution and its lifecycle guarantees.

`CONTEXT.md` currently defines a Highlight as reviewed localisation and a Highlight
attempt as selection, segmentation, and localisation review. Update these terms
to describe prompt-based, unreviewed segmentation. Update `backend/README.md` and
the old highlight spec's supersession notice for eager scheduling, polling, and
parallelism. Do not imply that user-requested safety review has been removed.

Likely implementation areas:

- `backend/app/models/schemas.py` and model prompts: optional concept output.
- `backend/app/assessments/service.py`: atomic initial attempt creation.
- `backend/app/annotations/provider.py`: concept requests, confidence parsing,
  candidate ranking, removal of selection/review calls.
- `backend/app/annotations/service.py` and worker/storage code: independent
  dispatch, claims, concurrent updates, and publication guards.
- `mobile/src/components/finding-highlight.tsx`, mobile domain/API data, and
  assessment/finding screens: discover and fetch existing jobs.
- `mobile/src/components/evidence-photo.tsx`: remove zoom and retain alignment.
- Deployment/local worker configuration, backend README, ADRs, and domain terms.

## Acceptance criteria and validation

1. An initial assessment uses one main-model analysis call. Each eligible finding
   supplies a short concept prompt and schedules one SAM call; highlighting makes
   no additional main-model calls and requests no model-generated bounding box.
2. Initial jobs exist before the assessment success response. They execute even
   if no finding is ever opened. Injected enqueue failure is recoverable from
   persisted intent without losing work or duplicating provider requests.
3. A controlled multi-finding test demonstrates provider requests overlapping:
   hold one attempt open while a sibling reaches ready. Exercise both the local
   worker and production dispatch path/configuration, including the 12-finding
   limit. Verify concurrent Firestore changes preserve sibling state.
4. Missing/invalid prompts and zero findings cause no SAM calls and preserve
   successful safety results. Unsupported configuration remains explicit.
5. Multiple candidates select the highest-scored valid result. Cover equal,
   absent, mixed, and invalid scores, invalid masks, malformed geometry, excessive
   output, and zero matches. Only one mask is displayed.
6. Opening/reopening/restarting only fetches existing work. Polling uses the
   two-second cadence while active, stops appropriately, and never drives job
   execution or model retries. Saved results appear after app closure/reconnection.
7. Timeout/provider failure affects only its finding. Duplicate delivery, rapid
   retry taps, and recovery cannot duplicate a started attempt. Explicit retry
   uses the saved prompt without main-model selection or review.
8. Follow-up/review creates no new segmentation job. Stale masks are absent from
   current evidence; historical masks retain their original photo/revision.
9. Zoom controls/modal are absent, including in historical evidence. Inline
   overlays remain aligned for portrait, landscape, and rotated photos. Labels
   accurately describe unreviewed AI output. Hide/report actions still work.
10. Concurrent deletion/revision/expiry cannot publish stale assets or restore
    deleted data. Existing authorization and private-asset checks remain valid.

Use focused backend tests for orchestration, ranking, overlap, idempotency, and
lifecycle races, and update the existing mobile/browser zoom and highlight-flow
checks. Record representative live SAM cases and observed instance-selection
limitations in `docs/demo.md` during implementation. Compare assessment-completion
to highlight-ready timing and provider call counts before/after; this spec makes
no measured performance or accuracy claim.
