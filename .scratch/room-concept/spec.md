# Generate a room concept from the initial assessment

## Purpose and agreed scope

Automatically generate an illustrative version of the assessed room in which the
AI attempts to address every potential hazard identified by the initial analysis.
Use the original room photo as a reference, preserving its layout, viewpoint and
overall style. The backend selects the image model through `MUSE_IMAGE_GEN_MODEL`.

The user confirmed the following design in the grilling interview:

1. Edit the same room rather than inventing a different room.
2. Start generation automatically once initial findings are saved. Do not wait
   for a tap, navigation or highlight completion, and do not delay assessment
   results while the image generates.
3. Generate once at the beginning using the initial findings. Later checklist,
   dismissal, chat or evidence changes never trigger another generation.
4. Save one successful image per assessment. A failed attempt may be retried
   explicitly; automatic model retries and regeneration after success are excluded.
5. Skip generation when there are no findings. Existing assessments are not
   backfilled.
6. Show the generated image only when the user opens it. The viewer shows the
   generated image alone, without the original in the same frame.
7. Use a backend-controlled prompt. Custom prompt editing, download and sharing
   controls are excluded.
8. Keep generated images private and delete them with their assessment/account.
   A generation problem must not break assessment, checklist or chat workflows.
9. Use the mobile-design skill when modifying the frontend.

The final scope was explicitly confirmed. This task creates a specification only;
application implementation, live model calls and deployment are subsequent work.

## Meaning and safety boundaries

Use **room concept** for this proposed domain term: a saved, AI-generated image
illustrating possible changes to the original assessed room. Add its definition
to `CONTEXT.md` during implementation.

The prompt should attempt to address all initial findings using their evidence
and recommendations, with household profiles/details as context. Preserve room
identity and unaffected features where possible; avoid gratuitous decoration or
unrelated changes. The initial set includes findings that users later resolve or
dismiss: the concept is a frozen illustration of the initial assessment.

The generated image is not a new photo, finding, finding-content revision or
highlight. It must never replace original evidence, enter subsequent finding-chat
context as evidence, resolve findings, update checklist statuses, or be presented
as proof that the physical room is safe. Generation may omit a requested change
or introduce visual errors; success means a valid image was generated and saved,
not that hazard removal was verified. No secondary safety certification/model
review is required by this feature.

Visible title: **AI-generated room concept**.

Visible explanatory copy:

> An illustration of suggested changes based on the original assessment. It may
> miss hazards or show inaccurate changes. It does not mean your room is safe.

Keep existing safety guidance and urgent-action recommendations accessible in the
assessment. Treat household text and photo text as untrusted contextual data,
never as instructions overriding the backend prompt.

## Automatic generation and persistence

At successful initial-assessment completion, atomically save the initial findings
and one room-concept job with its dispatch intent. A model failure must not undo
the assessment. If the completion commit fails, do not enqueue a job for findings
that were never saved.

Freeze the source photo identity, initial finding content/recommendations,
household profiles/details and prompt version. Keep this snapshot stable across
manual retries; capture the selected image model for the attempt. Do not substitute
later status/content changes or newly supplied evidence. Bound stored metadata
within the existing assessment document size guard; store image bytes in GCS.

| State | Meaning and allowed behavior |
| --- | --- |
| Not applicable | New assessment has no findings; no model request or viewer action |
| Unavailable | Feature lacks usable image configuration; assessment still completes |
| Queued | Intent is saved; durable dispatch may deliver the job |
| Running | A worker holds the attempt claim and may make one model request |
| Ready | One validated image is privately stored and published; terminal success |
| Failed | Generation, validation, persistence or deadline failed; manual Retry is available |

Older assessments without room-concept metadata have no concept and never start
one on read, open or app upgrade. Enabling configuration later does not
automatically backfill unavailable/older assessments.

Persist attempt identity, lifecycle timestamps/deadlines, dispatch intent,
claim/publication identity, source snapshot identity, safe failure category and
ready-asset metadata. Record a model/prompt version for diagnosis without logging
photos, secrets or full sensitive prompts. No version-history UI is required.

Use the durable Cloud Tasks/Scheduler and local-worker patterns in ADRs 0002–0004.
The work must survive screen changes and client disconnection. Request-bound
background tasks or a mobile timer are insufficient on Cloud Run. Clients only
observe status through authenticated reads/polling; opening the viewer never
queues work.

Claim attempts atomically so duplicate deliveries, Scheduler sweeps and concurrent
workers do not repeat a started model call. Recover dispatch for unstarted queued
work; mark interrupted/expired started work failed and require manual Retry.
Concurrent retry taps create at most one new active attempt. Once Ready, no
endpoint, duplicate delivery or navigation can replace/regenerate the result.

Set explicit queue, provider-call, lease and dispatch deadlines. The provider call
plus validation/upload must fit the lease, dispatch deadline and current 300-second
Cloud Run request limit. Do not reuse the short SAM timeout or assume a documented
image-generation latency guarantee. If the image service cannot finish within the
supported bounded worker request, surface a retryable failure; introducing a new
long-running execution platform is outside this spec. Tune limits in one backend
configuration and document their values during implementation.

Image work must coexist with chat, highlights and account cleanup: use bounded
dispatch/concurrency and preserve current independent claims and deletion fences.
No automatic provider retry or fallback is allowed, including SDK default retries.

## Muse adapter and deployment configuration

Add backend `MUSE_IMAGE_GEN_MODEL` configuration independently of
`MUSE_MAIN_MODEL` and `MUSE_SEGMENTATION_MODEL`. Read the chosen value from the
existing environment configuration; do not hardcode a model as a substitute.
Keep `MUSE_API_KEY` backend-only and use its existing secret delivery mechanism.
Image generation always uses Muse; there is no Groq image fallback.

An absent/blank image model or unusable image credentials disables this optional
feature without adding a new startup failure to otherwise valid core-service
configuration. Preserve existing validation for the main model provider. An
invalid/inaccessible image model returned by Muse produces a safe failure state.

Add a dedicated image-generation adapter/parser rather than forcing image output
through the current text/structured-JSON provider contract. The official
[Muse image-generation documentation](https://dev.meta.ai/docs/image-generation)
establishes these integration requirements:

- Send `POST https://api.meta.ai/v1/images/edits` with bearer authentication and
  the configured model. Use Meta's JSON edit contract: `prompt` is the frozen
  instruction and `images` contains one inline `image_url` data URL of the original
  photo. Do not make the source publicly readable or upload it to the Files API.
- Set `n: 1`, `response_format: "b64_json"`, `output_format: "jpeg"`, and
  `stream: false`. This is a one-shot edit without conversation history; do not
  send Responses-only fields such as `store`, `input`, `tools` or response IDs.
- Disable image search, web search and shell using top-level `tool_enablement`.
- Validate that `data` contains exactly one image and decode its `b64_json`.
  Reject URL-only results, malformed output and old Responses envelopes. Do not
  follow signed URLs or fall back to another endpoint.
- Validate actual image bytes independently of the echoed `output_format`.
  A requested `size` expresses aspect ratio, not exact returned pixel dimensions.

Use the app's durable job, not an unverified assumption that provider background
mode supports this image model. Do not stream provider reasoning to the viewer.

Propagate the model setting through local setup, `.env.example`, guided deployment,
release commands and Cloud Run environment updates. The release process currently
builds an explicit environment map, so a value in local `.env` alone is insufficient.
Repeated releases and revision rollback must carry the intended image-model
configuration. No `EXPO_PUBLIC_` model credential or direct mobile provider call.

## Private assets, validation and deletion

Validate successful HTTP status, the single expected image item, bounded response
bytes/base64, decoded format, pixel dimensions and decodability before publication.
Reject empty, malformed, oversized or unexpected output. Select concrete bounded
byte/pixel limits and an app-supported display encoding during implementation;
do not trust a declared MIME type or reuse user-upload conversion blindly.

Store the image under the authenticated owner's assessment prefix in the private
photo bucket. Reserve asset identity before upload. Fence publication by the
current attempt, live assessment/account, claim and deadline, so a late result or
deleted assessment cannot reappear. Delete rejected, expired and orphaned uploads.
Extend asset discovery/cleanup beyond its current annotation-mask naming filter.

Assessment/account deletion removes concept metadata, source snapshot and generated
objects using the existing retryable cross-store deletion mechanism. Deletion
must win races with queued workers, retries and uploads. Retain versioning/soft-delete
policy and backend-only bucket access.

Serve ready images through an owner-authenticated backend route with the current
revocation checks, `Cache-Control: no-store` and `nosniff` conventions. Do not expose
provider URLs, public object URLs, raw base64 or provider credentials in assessment
JSON. Preserve account-scoped client cleanup and avoid persistent private-image
caching across sign-out/account deletion.

## Frontend experience

Frontend implementation must apply the **mobile-design** skill at
`.codex/skills/mobile-design/SKILL.md` from the repository root. Use its platform,
accessibility and visual-design guidance alongside the current app theme.

Place an unobtrusive **View room concept** entry on the completed assessment
screen. Show generation status without automatically displaying the image or
interrupting assessment/checklist use. There is no ETA or fabricated percentage.

- Tapping while queued/running opens the concept view with **Generating room
  concept…** and an explanation that the user can return later.
- Ready opens the saved generated image, its title and explanatory copy. Fit the
  full image without misleading cropping; provide a usable way to inspect detail
  on a phone. Keep normal accessible back/close navigation.
- Failed shows a concise error and **Retry**. Retry queues one new attempt from
  the frozen initial input; it never reruns assessment analysis.
- Unavailable shows a clear optional-feature unavailable state, without a dead
  retry control or exposing configuration details to users.
- No-findings and legacy assessments do not offer a generation action.

Show the generated image alone in its viewer. The original remains in the normal
assessment photo view. Do not add a side-by-side comparison, slider, automatic
image reveal, custom prompt field, export/share action or success-regeneration
control. Findings and checklist remain usable while generation runs or fails.

Poll bounded status reads only while the relevant app/view is active, following
existing patterns. Resume reads on return; jobs continue without the client.
Persist/map state so reopening an assessment or using another authenticated
installation retrieves the same result. Do not start jobs from hydration or poll
responses. Stop observation and clear private view state on account changes.

Preview mode uses explicitly simulated states/images in its separate local data;
it makes no real generation request. Support loading, ready, unavailable, failed
and retry interactions. Verify narrow screens, larger text, screen-reader labels,
status announcements, safe areas and platform back behavior on Android/iOS.

## Integration references and architectural fit

Read-only inspection identified:

- `backend/app/config.py` and `.env.example`: model settings currently omit image
  generation; the main/segmentation models already have separate configuration.
- `backend/app/models/providers/base.py` and `muse.py`: existing contracts parse
  structured text and chat streams, not generated images.
- `backend/app/assessments/` and `backend/app/annotations/`: initial-completion
  integration and durable claim/dispatch/publication precedents.
- `backend/app/storage/photos.py`: private asset handling, prefix deletion and
  annotation-specific orphan discovery need extension.
- `backend/app/api/routes.py`: authenticated asset serving and internal-worker
  authentication conventions.
- `mobile/app/assessment/[id].tsx`: completed assessment viewer entry; frontend
  domain/API/storage/context mappings also need the new persisted state.
- `scripts/deploy.py`, `scripts/deploy-gcp.py`, `scripts/terraform-gcp.py`:
  configuration propagation and deployment checks.

No conflict with ADRs 0001–0004 was identified. This extends their managed-storage,
durable-work and deletion-fence patterns. It promotes the illustrative redesign
stretch goal in `CONTEXT.md` into the approved scope without changing the rule
that a redesign is never a validated safety improvement.

## Acceptance criteria and verification

1. A newly completed assessment with findings atomically records one queued
   concept job; initial findings return without waiting for generation. No-findings,
   failed initial analyses and legacy reads do not call the image provider.
2. Generation uses the original photo, frozen initial findings, recommendations
   and household context, the configured image model, stateless request and no
   web/image/shell grounding tools. Later status/chat changes do not change input.
3. Duplicate deliveries, simultaneous retries, reopening and worker recovery
   never duplicate a started provider call. Failure requires manual Retry;
   successful results are immutable and have no regenerate action.
4. Jobs survive mobile navigation/disconnection and persist across backend/app
   restarts. Queue expiry/interrupted work becomes a visible failure within bounded
   deadlines. Check that image work does not block chat/highlight/deletion recovery.
5. Adapter tests cover mixed output types, completed images, provider errors,
   refusal/missing image, malformed base64, oversized/invalid image data and
   timeouts. Feature unavailability never invalidates successful core assessment.
6. Deletion-race tests cover before upload, after upload/before publication, late
   worker completion and orphan sweeping. Other accounts cannot read status,
   retry work or retrieve the image. No sensitive image payloads/credentials enter logs.
7. The frontend initially shows status/entry only. Tapping opens a single-image
   viewer or the correct pending/error state. Retry, restart, second installation,
   account switch and preview preserve their specified behavior. No image display
   modifies findings, evidence, highlights or checklist status.
8. Deployment checks confirm `MUSE_IMAGE_GEN_MODEL` reaches the Cloud Run revision
   alongside backend-only secret access, including repeated releases. Document
   setup and operational limits in backend/deployment documentation.
9. Use focused backend workflow/provider/storage tests and frontend state/API
   integration checks, then relevant existing checks. Apply mobile-design during
   UI work and record actual native accessibility/device verification. A small
   manual room example checks room identity and intended visual edits without
   claiming hazard-removal accuracy. Record unavailable provider/device checks.

## Comments

The user explicitly confirmed the agreed scope before this specification was
created. No implementation, deployment or real image generation was performed
as part of the spec task.


Endpoint amendment confirmed 2026-11-01: the user approved the JSON
`/v1/images/edits` contract above, replacing the initial Responses image contract.
Only the room-concept adapter changes. Preserve saved images, durable jobs,
timeouts and manual retry rules; no automatic regeneration or endpoint fallback.
