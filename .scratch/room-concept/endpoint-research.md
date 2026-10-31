# Room-concept endpoint research

Reviewed 2026-11-01 against official Meta documentation; no provider calls or adapter changes.

**Recommendation:** `/v1/images/edits` best matches our one-shot photo edit; `/v1/images/generations` is text-to-image. Responses remains valid. Migration would simplify the interface, without demonstrated fidelity or latency gains. [Image-generation guide](https://dev.meta.ai/docs/image-generation#one-off-generation)

| Endpoint | Fit for this task |
| --- | --- |
| `/v1/images/generations` | Poor: does not provide the documented source-image edit contract. |
| `/v1/images/edits` | Best semantic fit: one source photo plus the frozen initial findings in an edit prompt. |
| `/v1/responses` | Valid current implementation: one user message with `input_text` and inline `input_image`, `store:false`, no history. |

These are the same `muse-image-1.0` model, not documented fidelity tiers. Meta lists both image generation and editing on the model and supports Responses and single-shot images APIs. [Models](https://dev.meta.ai/docs/models#muse-image)

For `/images/edits`, raw HTTP JSON accepts `images:[{"image_url":"data:image/jpeg;base64,..."}]`; SDK calls upload bytes as multipart. Neither needs a publicly readable source or Files API upload. [Edit API](https://dev.meta.ai/docs/api-reference/images/edit-image)

For Responses, the official photo-editing recipe confirms that a first-turn source photo and edit instruction produce an edited image. Select completed `image_generation_call` output by type and decode `result`; accompanying text/reasoning is not the image. Explicitly describe unchanged layout, viewpoint, room identity and unaffected objects. Results are nondeterministic and may change other areas: preservation is intent, not a guarantee. [Photo-editing recipe](https://dev.meta.ai/docs/cookbook/image-editing-with-reasoning)

Set all three flags false: `enable_image_search`, `enable_web_search`, `enable_shell`. Images uses top-level `tool_enablement`; Responses places flags in its `image_generation` tool. Images returns `data[].b64_json` by default; `response_format:"url"` instead returns a temporary signed URL. Prefer base64, validate and save privately: this avoids another fetch and expiring URL handling. Tool disabling can improve speed; no endpoint-specific latency guarantee was found. [Image-generation guide](https://dev.meta.ai/docs/image-generation)

Choose `n:1`, `response_format:"b64_json"` and explicit `output_format` for edits. Supported encodings are PNG/JPEG/WebP; `size` controls aspect ratio, not exact pixels. Image count is 1–10. `reasoning_strength:"low"` skips internal self-refinement; this is separate from conversational refinement, and one-shot does not require low reasoning. [Images schemas](https://dev.meta.ai/docs/api-reference/images/schemas)

Guide limits: 1–10 edit inputs, 16:1 maximum aspect ratio; no masks or `input_fidelity`. [Image-generation guide](https://dev.meta.ai/docs/image-generation#errors) Retain application byte/pixel/time limits; no exact image-generation upload-byte or latency guarantee was established.

`store:false` disables Responses persistence for retrieval/chaining. [Responses schemas](https://dev.meta.ai/docs/api-reference/responses/schemas) It does **not** establish zero provider retention. Meta ZDR needs separate organization enablement, varies by model and retains legal/misuse exceptions; qualifying policy-violation content may remain up to two years. [Meta ZDR](https://dev.meta.ai/help/policies-and-privacy/zero-data-retention)

Current spec explicitly requires Responses. Any future edit-endpoint migration should update that contract and adapter tests together. The independently diagnosed JPEG `is_animated` decoding failure is local validation and supplies no evidence against either endpoint. No migration is needed to fix it. No measured latency/fidelity comparison was performed.
