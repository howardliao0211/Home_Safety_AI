import { test } from "node:test";
import assert from "node:assert/strict";
import { assessmentTitle } from "../src/domain/history";

test("history titles preserve eight words and truncate only longer titles", () => {
  assert.equal(assessmentTitle(undefined), "Room assessment");
  assert.equal(assessmentTitle("   "), "Room assessment");
  assert.equal(assessmentTitle("  Living Room Review  "), "Living Room Review");
  assert.equal(
    assessmentTitle("Living room with a reading corner beside windows"),
    "Living room with a reading corner beside windows",
  );
  assert.equal(
    assessmentTitle("Living room with a reading corner beside the window"),
    "Living room with a reading corner beside the…",
  );
  assert.equal(
    assessmentTitle("Living\troom\nwith a reading corner beside the window"),
    "Living room with a reading corner beside the…",
  );
});
