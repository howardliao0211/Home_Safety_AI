import assert from "node:assert/strict";
import { test } from "node:test";
import { overviewHighlights } from "../src/domain/highlights";
import type { Annotation, Assessment, Finding } from "../src/domain/model";

const ready = (id: string, extra: Partial<Annotation> = {}): Annotation => ({
  id,
  revision: "initial",
  attempt: 1,
  state: "ready",
  photo_id: "original",
  photo_kind: "original",
  image_digest: "abc",
  width: 120,
  height: 90,
  orientation: 1,
  ...extra,
});
const finding = (
  id: string,
  severity: Finding["severity"],
  annotation: Annotation | null,
  extra: Partial<Finding> = {},
): Finding => ({
  id,
  title: id,
  category: "c",
  severity,
  evidence: "e",
  recommendation: "r",
  shortAction: "s",
  uncertainty: "u",
  status: "open",
  note: "",
  submissions: [],
  contentRevision: "initial",
  annotation,
  ...extra,
});
const assessment = (findings: Finding[]): Assessment => ({
  id: "a",
  createdAt: "2026-11-01T00:00:00Z",
  photo: { id: "original", label: "Room", digest: "abc" },
  profiles: [],
  scenario: "hazards",
  status: "complete",
  attempts: 1,
  findings,
});

test("draws every ready, current, original-photo mask for open findings in stable order", () => {
  const result = overviewHighlights(
    assessment([
      finding("low", "Low", ready("m1")),
      finding("high", "High", ready("m2")),
      finding("medium", "Medium", ready("m3")),
    ]),
  );
  assert.deepEqual(
    result.masks.map((m) => [m.findingId, m.severity]),
    [
      ["low", "Low"],
      ["high", "High"],
      ["medium", "Medium"],
    ],
  );
  assert.equal(result.openCount, 3);
  assert.equal(result.pending, false);
});

test("resolved, dismissed, pending, failed, reported and mismatched masks are not drawn", () => {
  const result = overviewHighlights(
    assessment([
      finding("resolved", "High", ready("m1"), { status: "resolved" }),
      finding("dismissed", "High", ready("m2"), { status: "dismissed" }),
      finding("queued", "High", ready("m3", { state: "queued" })),
      finding("processing", "High", ready("m4", { state: "processing" })),
      finding("failed", "High", ready("m5", { state: "failed" })),
      finding("reported", "High", ready("m6", { state: "reported" })),
      finding("unavailable", "High", ready("m7", { state: "unavailable" })),
      finding("none", "High", null),
      finding("stale", "High", ready("m8"), { contentRevision: "rev-2" }),
      finding(
        "follow-up photo",
        "High",
        ready("m9", { photo_kind: "follow-up" }),
      ),
      finding("other photo", "High", ready("m10", { photo_id: "other" })),
      finding("other digest", "High", ready("m11", { image_digest: "zzz" })),
      finding("bad geometry", "High", ready("m12", { width: 0 })),
      finding("ok", "Medium", ready("m13")),
    ]),
  );
  assert.deepEqual(
    result.masks.map((m) => m.findingId),
    ["ok"],
  );
  assert.equal(result.openCount, 12);
  assert.equal(result.pending, true);
});

test("reopening a finding restores its still-eligible mask", () => {
  const base = finding("cable", "Medium", ready("m1"), { status: "dismissed" });
  assert.equal(overviewHighlights(assessment([base])).masks.length, 0);
  const reopened = { ...base, status: "open" as const };
  assert.equal(overviewHighlights(assessment([reopened])).masks.length, 1);
});
