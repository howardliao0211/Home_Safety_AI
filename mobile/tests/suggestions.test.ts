import assert from "node:assert/strict";
import { test } from "node:test";
import { fromServer, type RemoteAssessment } from "../src/api/backend-client";
import {
  fixtureFindings,
  fixtureSuggestions,
} from "../src/api/preview-service";
import { createAssessment } from "../src/domain/model";

const remote = (extra: Partial<RemoteAssessment> = {}): RemoteAssessment => ({
  id: "33333333-3333-4333-8333-333333333333",
  created_at: "2026-11-01T01:00:00Z",
  status: "complete",
  attempts: 1,
  error: null,
  photo: { id: "photo", uploaded: true },
  profiles: [],
  summary: null,
  findings: [],
  ...extra,
});

test("server suggestions are kept as structured items, distinct from legacy summaries", () => {
  const items = ["First priority.", "Second priority.", "Third priority."];
  const saved = fromServer(remote({ suggestions: items }));
  assert.deepEqual(saved.suggestions, items);
  assert.equal(saved.summary, undefined);
  assert.deepEqual(fromServer(remote({ suggestions: [] })).suggestions, []);
  const legacy = fromServer(remote({ summary: "Old prose. Two sentences." }));
  assert.equal(legacy.summary, "Old prose. Two sentences.");
  assert.equal(legacy.suggestions, undefined);
});

test("preview suggestions are three household-aware items, and none without findings", () => {
  const assessment = createAssessment({
    photo: { id: "p", label: "Living room", sample: "living" },
    profiles: ["Older adult"],
    scenario: "hazards",
    householdContext: "Grandpa uses a walker",
  });
  const items = fixtureSuggestions(assessment, fixtureFindings("hazards"));
  assert.equal(items.length, 3);
  assert.equal(new Set(items).size, 3);
  assert.match(items.join(" "), /walker|older adult/i);
  const general = fixtureSuggestions(
    { ...assessment, profiles: [], householdContext: "" },
    fixtureFindings("hazards"),
  );
  assert.equal(general.length, 3);
  assert.deepEqual(fixtureSuggestions(assessment, []), []);
});
