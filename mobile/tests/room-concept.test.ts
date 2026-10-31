import assert from "node:assert/strict";
import test from "node:test";
import {
  mergeRoomConcept,
  previewRoomConcept,
  conceptStatus,
} from "../src/domain/room-concept";
import { BackendClient } from "../src/api/backend-client";

test("late observation cannot replace a ready image or newer retry", () => {
  const ready = {
    state: "ready",
    attempt: 1,
    attempt_id: "a",
    can_retry: false,
  } as const;
  assert.equal(mergeRoomConcept(ready, { ...ready, state: "running" }), ready);
  const retry = {
    ...ready,
    state: "queued",
    attempt: 2,
    attempt_id: "b",
  } as const;
  assert.equal(mergeRoomConcept(retry, { ...ready, state: "failed" }), retry);
});

test("preview covers pending, failure, unavailable and no-findings without real calls", () => {
  assert.equal(previewRoomConcept("hazards", true).state, "queued");
  assert.equal(previewRoomConcept("uncertain", true).state, "failed");
  assert.equal(previewRoomConcept("hazards", false).state, "not_applicable");
  assert.equal(previewRoomConcept("hazards", true, true).state, "unavailable");
  assert.match(
    conceptStatus({ state: "queued", can_retry: false }),
    /Generating/,
  );
});

test("observation and image reads never enqueue generation; retry is explicit", async () => {
  const calls: { path: string; method: string }[] = [];
  const api = new BackendClient(
    { baseUrl: "https://backend.test", getToken: async () => "token" },
    async () => {},
    async (url, init) => {
      calls.push({ path: String(url), method: init?.method ?? "GET" });
      return String(url).endsWith("/image")
        ? new Response(new Uint8Array([1, 2, 3]))
        : Response.json({ state: "ready", can_retry: false });
    },
  );
  await api.roomConcept("assessment");
  await api.roomConceptImage("assessment");
  await api.retryRoomConcept("assessment", "retry-id");
  assert.deepEqual(
    calls.map((c) => c.method),
    ["GET", "GET", "POST"],
  );
  assert.match(calls[2].path, /room-concept\/retry$/);
});
