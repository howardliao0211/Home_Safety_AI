import assert from "node:assert/strict";
import { test } from "node:test";
import {
  completeSubmission,
  counts,
  createAssessment,
  emptyState,
  recoverInterrupted,
  retainedPhotos,
  type AppState,
} from "../src/domain/model";
import { fixtureFindings, previewService } from "../src/api/preview-service";
import { StateStore } from "../src/storage/state-store";

const draft = () => ({
  photo: { id: "photo", label: "Living room", sample: "living" as const },
  profiles: ["Baby" as const],
  scenario: "hazards" as const,
});

test("writes publish only after storage succeeds and serialize concurrent actions", async () => {
  let durable = emptyState();
  let published = emptyState();
  let rejectWrite = false;
  const store = new StateStore(
    {
      load: async () => durable,
      save: async (next) => {
        await new Promise((resolve) => setTimeout(resolve, 4));
        if (rejectWrite) throw new Error("Storage full");
        durable = structuredClone(next);
      },
    },
    (next) => {
      published = next;
    },
  );
  await store.load();
  const one = createAssessment(draft());
  const two = { ...one, id: "second" };
  await Promise.all([
    store.update((s) => ({ ...s, assessments: [...s.assessments, one] })),
    store.update((s) => ({ ...s, assessments: [...s.assessments, two] })),
  ]);
  assert.deepEqual(
    published.assessments.map((a) => a.id),
    [one.id, "second"],
  );
  rejectWrite = true;
  await assert.rejects(
    store.update((s) => ({ ...s, assessments: [] })),
    /Storage full/,
  );
  assert.equal(store.state.assessments.length, 2);
  assert.equal(published.assessments.length, 2);
  rejectWrite = false;
  await store.update((s) => ({ ...s, draft: draft() }));
  assert.ok(store.state.draft);
});

test("interrupted analysis and linked checks recover as manual retries with evidence intact", () => {
  const assessment = createAssessment(draft());
  const findings = fixtureFindings("uncertain");
  findings[0].submissions.push({
    id: "input",
    kind: "follow-up",
    status: "running",
    attempts: 1,
    text: "My answer",
    photo: draft().photo,
  });
  const state: AppState = {
    ...emptyState(),
    assessments: [{ ...assessment, status: "running", findings }],
  };
  const recovered = recoverInterrupted(state).assessments[0];
  assert.equal(recovered.status, "failed");
  assert.equal(recovered.findings[0].submissions[0].status, "failed");
  assert.equal(recovered.findings[0].submissions[0].text, "My answer");
  assert.equal(recovered.findings[0].submissions[0].photo?.id, "photo");
  assert.equal(state.assessments[0].status, "running");
});

test("follow-up revises exactly one submission without resolving or duplicating a finding", () => {
  const finding = fixtureFindings("uncertain")[0];
  finding.submissions.push({
    id: "input",
    kind: "follow-up",
    status: "running",
    attempts: 2,
    text: "",
    photo: draft().photo,
  });
  const result = completeSubmission(finding, "input", "Sample feedback");
  const repeated = completeSubmission(result, "input", "Sample feedback");
  assert.equal(repeated.submissions.length, 1);
  assert.equal(repeated.status, "open");
  assert.equal(repeated.followUp?.state, "answered");
  assert.equal(repeated.submissions[0].status, "complete");
  assert.match(repeated.uncertainty, /cannot establish/);
});

test("user reviews preserve resolved and dismissed statuses and do not consume a follow-up", () => {
  for (const status of ["resolved", "dismissed"] as const) {
    const finding = { ...fixtureFindings("uncertain")[0], status };
    finding.submissions.push({
      id: "review",
      kind: "review",
      status: "running",
      attempts: 1,
      text: "",
      photo: draft().photo,
    });
    const result = completeSubmission(finding, "review", "Your decision");
    assert.equal(result.status, status);
    assert.equal(result.followUp?.state, "available");
  }
});

test("photo retention includes older assessments, drafts, and failed linked submissions", () => {
  const assessment = createAssessment(draft());
  const findings = fixtureFindings("uncertain");
  findings[0].submissions.push({
    id: "review",
    kind: "review",
    status: "failed",
    attempts: 1,
    text: "",
    photo: { id: "review-photo", label: "Close up", uri: "file:///review.jpg" },
  });
  const state: AppState = {
    ...emptyState(),
    draft: { ...draft(), photo: { ...draft().photo, id: "draft-photo" } },
    assessments: [
      { ...assessment, findings },
      {
        ...assessment,
        id: "older",
        photo: { ...assessment.photo, id: "older-photo" },
      },
    ],
  };
  assert.deepEqual(
    retainedPhotos(state)
      .map((p) => p.id)
      .sort(),
    ["draft-photo", "older-photo", "photo", "review-photo"],
  );
  const deleted = {
    ...state,
    assessments: state.assessments.filter((a) => a.id !== assessment.id),
  };
  assert.deepEqual(
    retainedPhotos(deleted)
      .map((p) => p.id)
      .sort(),
    ["draft-photo", "older-photo"],
  );
});

test("checklist counts distinguish user resolution and dismissal; no-hazards is a genuine empty fixture", () => {
  const findings = fixtureFindings("hazards");
  findings[0].status = "resolved";
  findings[1].status = "dismissed";
  assert.deepEqual(counts(findings), { resolved: 1, dismissed: 1, open: 1 });
  assert.deepEqual(fixtureFindings("clear"), []);
});

test("analysis error is explicit, then retry produces stable finding identifiers", async () => {
  const assessment = {
    ...createAssessment(draft()),
    scenario: "analysis-error" as const,
    attempts: 1,
  };
  await assert.rejects(previewService.assess(assessment), /could not finish/);
  const results = await previewService.assess({ ...assessment, attempts: 2 });
  assert.deepEqual(
    results.map((f) => f.id),
    fixtureFindings("hazards").map((f) => f.id),
  );
});
