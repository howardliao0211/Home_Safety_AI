# On-demand hazard object highlighting

> **Superseded in part by `../eager-finding-segmentation/spec.md` (ADR 0003).**
> Highlights now start when the initial assessment completes, from a segmentation
> prompt in the assessment response. Opening a finding only fetches and polls saved
> attempts; attempts run concurrently; main-model selection and localisation review
> and photo zoom are removed; follow-up/review revisions are not highlighted.
> User-requested safety reviews are unchanged.

Confirmed through a grilling session on 2026-10-28.

## Problem and outcome

Users currently locate a finding's visible evidence using text and an unannotated
room photo. A finding should optionally highlight one main object so the user can
quickly locate the concern. The finding's existing evidence and recommendation
continue to explain why the object matters.

The assessment screen stays fast and always displays the original image without
annotations. Opening a finding shows its content immediately and starts a separate,
asynchronous highlighting operation. Highlighting never delays safety analysis,
publication of findings, or checklist use.

This is a complete feature specification, not a feasibility experiment. Assume
MUSE segmentation capability is sufficient. Object selection, review, validation,
and operational failure handling remain required even under that assumption.

## Settled scope

- One main object per finding, even when the concern involves several objects.
- Prefer the object the recommended action primarily concerns. For example, if
  the recommendation is to move curtains away from a heater, highlight the curtains.
- Highlight only visible evidence. An outlined cabinet does not establish whether
  it is anchored, and an annotation does not verify that a recommendation is safe.
- No suitable single object means a text-only finding; do not invent a region.
- Initial, follow-up, and user-review photos are eligible supporting evidence.
- Existing assessments gain highlighting on demand without rerunning safety analysis.
- Use MUSE, including the existing `MUSE_SEGMENTATION_MODEL` environment setting.
- No assessment overview annotations, automatic pre-generation for every finding,
  multiple highlighted objects per finding, user-drawn masks, automatic model
  regeneration, or automatic provider switching.

## User experience

### Assessment screen

Preserve the existing assessment and checklist workflow. Show the original image
and findings as soon as safety analysis completes. Do not wait for, display, or
automatically request annotations here. Opening a finding triggers its operation.

### Finding screen

1. Show the finding's text and photo immediately.
2. Request or reuse highlighting for the current finding revision.
3. While queued or processing, keep the screen interactive. Show a small
   “Highlight queued…” or “Preparing highlight…” status; do not cover the content
   with a blocking spinner.
4. When ready, display the selected supporting photo with a translucent mask and
   clear outline around the single reviewed object.
5. Display the full photo without cropping, support a zoomable view, and provide
   “Hide highlights.” The image and mask must share the same coordinate transform.
6. If a different supporting photo is selected, identify it as the original,
   follow-up, or review photo. Never silently place a mask over the initially
   displayed photo when the mask belongs to another image.

Retain readable text describing the evidence; neither color nor the mask is the
only way to understand the finding. Controls require accessible labels. Existing
finding severity, uncertainty, disclaimer, and status controls remain available.

Leaving the screen does not cancel processing. Reopening, app restart, or network
reconnection reconnects to the existing operation or loads the saved result.
The hide toggle affects display only. “Wrong object highlighted” is a separate
action: hide that annotation persistently and record feedback without changing
the finding's content, checklist state, or `open`/`resolved`/`dismissed` status.
Do not automatically regenerate a reported annotation. Offer an explicit retry.

### Unavailable highlights and retry

An unsuitable object, ambiguous selection, rejected review, empty segmentation,
invalid output, processing error, or timeout leaves the finding usable without
a mask. Show a short annotation-specific explanation and an explicit retry action
when another attempt is supported. A configuration that does not support MUSE
highlighting explains that it is unavailable; it does not silently change providers.

Opening or refreshing a terminal result must not automatically retry it. A manual
retry creates one new attempt for the same photo/evidence revision and preserves
attempt history. Repeated retry taps while an attempt is queued or running reuse
that attempt. Previously reported masks stay hidden while a retry runs.

Safety-analysis failures retain the existing assessment error and retry flow.
Annotation success cannot convert a failed analysis into a successful assessment.

## Processing pipeline

### 1. Select the evidence and object

The main MUSE model receives the current finding and its available supporting
evidence. It selects exactly one source photo and one main object, or explicitly
reports that no suitable object exists. The object must be supported by that
finding's evidence. Do not choose an unrelated photo merely because it contains
a similar object.

The selection result identifies the photo, object description, and sufficient
spatial guidance to distinguish repeated instances. A generic noun alone is not
sufficient when the photo contains several plausible matching objects. Use the
segmentation API's supported spatial guidance or select the intended instance
from candidates; the final output must refer to one object instance.

Selection runs inside the annotation operation, not the safety-analysis request.
It must not mutate the safety finding, its uncertainty, or its recommendation.

### 2. Segment one object

Call the model configured by `MUSE_SEGMENTATION_MODEL` using backend-only MUSE
credentials. Use a separate adapter/parser for segmentation output rather than
assuming the existing structured safety-analysis response parser can decode masks.

Allow one segmentation pass per attempt. If the response contains several matching
instances, they are candidates, not permission to display every matching object.
Do not run a combined request to segment all hazards in an assessment.

### 3. Review before publication

The main model receives the original source photo, finding, and candidate overlay
with identifiable candidates. It approves exactly one object instance or rejects
the annotation. Review must check that the highlighted instance matches the
finding's visible evidence, including the intended instance among similar objects.
It may select an existing candidate; it cannot trigger another segmentation pass.

Allow one review pass per attempt. Rejection, ambiguity, malformed review output,
or review failure produces a text-only result. Never publish an unreviewed mask.
The review decision concerns localisation only and must not silently revise the
safety finding or imply professional verification.

### 4. Validate and save

Validate the selected photo's membership in the assessment, finding revision,
source dimensions, orientation, mask decoding, nonempty mask, and finite in-bounds
geometry before publication. Use validated normalized coordinates for region
metadata, with a top-left origin and axes in `[0, 1]`. Store a source-aligned mask
with explicit dimensions and orientation. Reject invalid geometry rather than
rendering a misleading region.

Several disconnected mask components are acceptable only when they represent
visible parts of the same object. A ready result cannot contain several distinct
object instances. Segmentation confidence is not finding severity or safety
confidence and must not be presented as either.

## Jobs, queueing, and persistence

- Persist jobs and results in Firestore; store mask assets in private GCS.
- At most one annotation job may actively process per assessment. Queue additional
  requests in opening order. Different assessments do not share this product-level
  serialization rule.
- Deduplicate requests using assessment ID, finding ID, finding-content revision,
  and attempt identity. Once selected, also bind the result to the exact photo ID
  and image digest. Use atomic claims/leases so concurrent workers cannot publish
  two attempts for the same job.
- The processing budget is 30 seconds from claiming the job, including object
  selection, segmentation, review, validation, and publication. Queue waiting time
  is separate. Bound provider calls by the remaining budget; the existing generic
  model timeout must not extend this operation's deadline.
- No automatic model retries or regeneration. A worker lost mid-attempt becomes
  a failed/interrupted attempt after lease expiry and requires manual retry.
  Duplicate delivery of the same job must not start duplicate provider calls.
- Navigation and app lifetime do not own job execution. The worker must survive
  mobile disconnection. Use durable dispatch compatible with Cloud Run; an
  in-process FastAPI background task or client polling as the execution driver
  does not satisfy this requirement.
- Recommended production mechanism: Cloud Tasks invokes an authenticated worker
  endpoint, with Firestore as the authoritative queue and lease store. Persist
  pending dispatch intent so enqueue failure can be recovered without losing work.
  Infrastructure dispatch recovery may redeliver the same job but must never
  automatically repeat a started model attempt.
- Provide a local worker/dispatcher path using the same job state transitions and
  existing storage emulators. Production dispatch must not be required to develop
  or verify the feature locally.
- Expired, deleted, or superseded work cannot publish a current annotation.
  Late provider output after timeout is discarded. Release the queue so later
  findings can proceed after a terminal result.

Suggested public state contract:

| State | Meaning | Finding display |
| --- | --- | --- |
| `not_requested` | No attempt for this revision | Original/supporting photo; request on opening |
| `queued` | Waiting behind another annotation | Photo and text with queued status |
| `processing` | Selection, segmentation, or review underway | Photo and text with progress status |
| `ready` | Validated and reviewed object mask saved | Supporting photo and toggleable highlight |
| `unavailable` | No suitable object, no match, or review rejection | Text-only explanation; manual retry |
| `failed` | Provider, validation, interruption, or timeout error | Text-only explanation; manual retry |
| `reported` | User identified an incorrect highlight | Persistently hidden mask; feedback saved; manual retry |

Unsupported configuration is a capability response, not a model attempt. It must
not enqueue work or produce a retry loop.

## Evidence revisions and history

Add a stable finding-content revision separate from checklist status. Successful
follow-up or review analysis creates a new content revision and preserves the
previous evidence/annotation snapshot. Failed safety analysis preserves the current
finding and annotation. Resolving, dismissing, reopening, or adding a status note
does not by itself create a new content revision or invalidate its annotation.

Publish revised findings immediately after safety analysis. If the finding is
currently visible, request its new annotation; otherwise wait until it is opened.
Never show the previous revision's mask as the current finding's highlight.

Keep older annotations available alongside their historical finding evidence and
source photo. Text-only follow-ups may still select an earlier supporting photo;
they must not imply that invisible changes have been verified. Never transfer a
mask between photos or infer resolution from an object's absence.

For existing assessments, assign an initial revision lazily and annotate their
current saved content. Do not require backfilling every record or fabricate older
finding snapshots that were never stored. Missing legacy photos produce an explicit
unavailable result rather than silently substituting another image.

## Backend contract

Extend finding data additively with content revision and annotation metadata.
Return lightweight job/result metadata in normal reads, not raw masks in every
assessment response. Do not expose internal leases, storage keys, provider payloads,
or credentials.

Proposed endpoints beneath
`/v1/assessments/{assessment_id}/findings/{finding_id}`:

| Endpoint | Purpose |
| --- | --- |
| `POST /annotations` | Idempotently request/reuse an attempt for an expected content revision; explicit retry intent creates a new attempt only after a terminal result |
| `GET /annotations/{annotation_id}` | Read job state and reviewed result metadata |
| `GET /annotations/{annotation_id}/mask` | Return an authorized, source-aligned mask asset |
| `POST /annotations/{annotation_id}/feedback` | Idempotently record `wrong_object` feedback and hide that result |

A newly accepted asynchronous request returns `202` and an operation identifier;
reused terminal results may return `200`. Reject stale revision requests with
`409` so the client refreshes the finding. Poll while the relevant screen is active,
stop on a terminal result or navigation, and resume on reopening; polling does not
start model work.

Persist annotation ID, revision, source photo identity/digest/dimensions, target
description, state/reason, attempt and timing data, review decision, validated
region metadata, private mask reference, and user feedback. Preserve sufficient
revision evidence to render historical annotations accurately. Keep internal model
diagnostics separate from the public response.

Use the existing demo bearer authorization and `X-Device-ID` assessment scoping for
every client operation, mask read, retry, and feedback request. A worker endpoint
uses service authentication and is not exposed as an unauthenticated job trigger.

## Configuration, storage, and deletion

Use backend-only `MUSE_API_KEY`, `MUSE_MAIN_MODEL`, and
`MUSE_SEGMENTATION_MODEL`. The last setting already exists in the root `.env`;
implementation must add explicit settings validation and deployment wiring without
copying credentials into the spec, repository, mobile bundle, or logs. Other
provider configurations remain usable for text/photo findings with highlighting
explicitly unavailable; no automatic provider switching.

Mask assets inherit private photo storage, backend-only access, retention, and
retryable deletion semantics from ADR 0001. Assessment deletion marks the assessment
as deleting, cancels queued annotation work, fences publication by running work,
and removes annotation metadata and assets alongside photos. Clean up any assets
written by a losing, interrupted, or deletion-racing attempt. Deletion must remain
retryable across Firestore and GCS; do not recreate a deleted assessment to save a
late result.

Log operation and correlation identifiers, assessment/finding/revision identifiers,
stage, duration, and diagnostic error category. Keep credentials, photo payloads,
mask payloads, and unnecessary household content out of logs.

## Acceptance criteria

1. Assessment analysis returns independently of annotation latency or failure;
   the assessment screen always displays an unannotated original photo.
2. Opening a finding immediately shows text and photo, triggers one annotation
   request, and updates asynchronously after mandatory review.
3. With several similar objects, only the intended main instance is highlighted.
   Several findings may independently highlight different objects in one photo.
4. A relationship-based finding highlights one action-relevant main object. A
   concern without a suitable visible object remains text-only.
5. Full-image display, portrait/landscape images, rotation/orientation metadata,
   and zoom keep the mask aligned. The hide toggle reveals the original evidence.
6. Rapidly opening findings queues them in order with one active job per assessment.
   Repeated opens, retry taps, and duplicate worker delivery do not duplicate work.
7. Leaving the screen, restarting the app, or reconnecting reuses persisted state.
   Backend restart does not erase queued work or silently restart a model attempt.
8. No-match, rejected review, malformed output, provider error, worker interruption,
   and deadline expiry preserve the finding and expose the appropriate explanation
   and manual retry. An unreviewed mask is never displayed.
9. Follow-up and review revisions publish without waiting for annotation. No stale
   mask is presented as current, even when an older job completes afterward.
10. Historical annotations display their own evidence and photo. Existing
    assessments work lazily without fabricated history or a mandatory bulk migration.
11. Wrong-object feedback persists across reopening and restart, hides the result,
    and leaves finding/checklist status unchanged. Retry requires explicit action.
12. Device scoping applies to annotation creation, reads, assets, feedback, and
    retries. Annotation output does not expose provider credentials or private URLs.
13. Deletion removes annotation assets and metadata, cancels queued work, and
    prevents in-flight jobs from restoring deleted data. Partial deletion is retryable.

Use focused backend tests for state transitions, deduplication, revision and
deletion races, and authorization; use mobile interaction checks for asynchronous
states, navigation, and mask alignment. Verify production-compatible durable
dispatch as well as local worker behavior. Record representative manual cases and
observed limitations in `docs/demo.md`; do not claim measured detection accuracy
from this small demonstration or create a separate evaluation framework.

## Project alignment and references

`CONTEXT.md` currently lists annotations as a stretch goal requiring reliable
localisation and validated normalized coordinates. This spec defines that feature;
it does not silently reprioritize the original one-week MVP. Coordinate validation
and conservative text-only fallback remain required. ADR 0001's Firestore/GCS
decision is preserved. Implementation should update domain documentation for
settled annotation/revision terminology and document any new dispatch architecture.

Current implementation touchpoints:

- `mobile/app/assessment/[id].tsx` and
  `mobile/app/finding/[assessmentId]/[findingId].tsx`: overview and detail flows.
- `mobile/src/components/ui.tsx`: current compact `PhotoView` crops images;
  finding annotation display requires a full-image transform shared with the mask.
- `mobile/src/domain/model.ts` and `mobile/src/api/backend-client.ts`: additive
  annotation state, job API, and asset access.
- `backend/app/models/schemas.py`, `backend/app/assessments/service.py`, and
  `backend/app/api/routes.py`: revisions, orchestration, and client contracts.
- `backend/app/models/providers/muse.py` and `backend/app/config.py`: dedicated
  segmentation handling, model review, and configuration.
- `backend/app/storage/`, `deploy/`, and local scripts: persistence, deletion,
  durable dispatch, and local worker support.

Provider references consulted during the session:

- [Meta media segmentation](https://dev.meta.ai/docs/media-segmentation): scene
  interpretation and object segmentation are separate responsibilities.
- [SAM overview](https://dev.meta.ai/docs/sam/overview): segmentation API integration.
- [Prompting SAM](https://dev.meta.ai/docs/sam/segmenting): concept prompts can match
  multiple instances; spatial guidance matters for selecting a particular object.
- [Reading segmentation output](https://dev.meta.ai/docs/sam/reading-segmentation):
  source geometry and mask decoding. Validate actual provider responses when
  implementing the adapter rather than treating proposed app contracts as provider
  response formats.
