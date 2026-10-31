import assert from "node:assert/strict";
import { test } from "node:test";
import {
  createAssessment,
  householdDetailsError,
  householdDetailsLength,
  isDraftDirty,
  type Draft,
} from "../src/domain/model";
import {
  BackendClient,
  fromServer,
  type RemoteAssessment,
} from "../src/api/backend-client";

const draft = (householdContext?: string): Draft => ({
  photo: { id: "photo", label: "Living room", sample: "living" },
  profiles: [],
  scenario: "hazards",
  ...(householdContext === undefined ? {} : { householdContext }),
});

test("creating an assessment trims outer whitespace and keeps internal spacing and line breaks", () => {
  const assessment = createAssessment(
    draft("  \n A 2-year-old\n\n  and  two cats \t\n"),
  );
  assert.equal(assessment.householdContext, "A 2-year-old\n\n  and  two cats");
});

test("whitespace-only and missing household details are blank", () => {
  assert.equal(createAssessment(draft(" \n\t ")).householdContext, "");
  assert.equal(createAssessment(draft()).householdContext, "");
  assert.equal(householdDetailsError(" \n "), undefined);
});

test("the 3,000 character limit counts the trimmed value in Unicode code points", () => {
  assert.equal(householdDetailsError("x".repeat(3000)), undefined);
  assert.equal(householdDetailsError(`  ${"x".repeat(3000)}\n`), undefined);
  assert.match(householdDetailsError("x".repeat(3001))!, /3,000 characters/);
  // A non-BMP character is one code point, as on the server.
  assert.equal(householdDetailsLength("🐈".repeat(3000)), 3000);
  assert.equal(householdDetailsError("🐈".repeat(3000)), undefined);
  assert.match(householdDetailsError("é🐈".repeat(1501))!, /3,000/);
});

test("overlong household details never become an assessment", () => {
  assert.throws(
    () => createAssessment(draft("x".repeat(3001))),
    /Keep household details to 3,000 characters or fewer\./,
  );
});

test("a draft with only household details needs discard protection", () => {
  assert.equal(
    isDraftDirty({
      profiles: [],
      scenario: "hazards",
      householdContext: "Cats",
    }),
    true,
  );
  assert.equal(
    isDraftDirty({ profiles: [], scenario: "hazards", householdContext: "  " }),
    false,
  );
  assert.equal(isDraftDirty({ profiles: [], scenario: "hazards" }), false);
  assert.equal(isDraftDirty({ profiles: ["Pet"], scenario: "hazards" }), true);
  assert.equal(isDraftDirty(draft()), true);
});

const remoteId = "22222222-2222-4222-8222-222222222222";
const remote = (household_context?: string): RemoteAssessment => ({
  id: remoteId,
  created_at: "2026-10-28T01:00:00Z",
  status: "ready",
  attempts: 0,
  error: null,
  photo: { id: "photo-id", uploaded: false },
  profiles: [],
  summary: null,
  findings: [],
  ...(household_context === undefined ? {} : { household_context }),
});

test("upload and retries send the saved household details alongside profiles", async () => {
  const forms: FormData[] = [];
  const client = new BackendClient(
    { baseUrl: "http://localhost:8000", getToken: async () => "token" },
    async (form) => form.append("photo", new Blob(["x"]), "room.jpg"),
    (async (_url: unknown, init?: RequestInit) => {
      forms.push(init!.body as FormData);
      return Response.json({ error: { code: "unavailable" } }, { status: 503 });
    }) as typeof fetch,
  );
  const assessment = {
    ...createAssessment({
      ...draft(" Two cats\n and a walker "),
      profiles: ["Pet"],
    }),
    id: remoteId,
  };
  await assert.rejects(client.upload(assessment));
  await assert.rejects(client.upload(assessment));
  assert.equal(forms.length, 2);
  for (const form of forms) {
    assert.equal(form.get("household_context"), "Two cats\n and a walker");
    assert.equal(form.get("profiles"), '["Pet"]');
  }
});

test("server household details are authoritative; older records map to blank", () => {
  const cached = fromServer(remote("Stale local text"));
  assert.equal(
    fromServer(remote("Saved on the server"), cached).householdContext,
    "Saved on the server",
  );
  assert.equal(fromServer(remote("")).householdContext, "");
  assert.equal(fromServer(remote()).householdContext, "");
  // A response without the field never erases context frozen at creation.
  assert.equal(
    fromServer(remote(), cached).householdContext,
    "Stale local text",
  );
});
