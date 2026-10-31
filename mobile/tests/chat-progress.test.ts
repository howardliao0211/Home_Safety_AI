import assert from "node:assert/strict";
import { test } from "node:test";
import {
  emptyConversation,
  isActive,
  isIncomplete,
  mergeConversation,
  type ChatTurn,
  type Conversation,
} from "../src/domain/chat";

const turn = (version: number, extra: Partial<ChatTurn> = {}): ChatTurn => ({
  id: "t1",
  question: "Q",
  answer: null,
  status: "running",
  error: null,
  created_at: "2026-11-01T00:00:00Z",
  finished_at: null,
  partial: "",
  version,
  ...extra,
});
const conversation = (...turns: ChatTurn[]): Conversation => ({
  ...emptyConversation(),
  turns,
});

test("newer snapshots replace older ones; late older snapshots are ignored", () => {
  const partial = conversation(turn(3, { partial: "Keep the" }));
  const final = conversation(
    turn(5, { status: "complete", answer: "Keep the route clear." }),
  );
  assert.equal(mergeConversation(partial, final).turns[0].status, "complete");
  // A late partial cannot replace the final answer.
  const merged = mergeConversation(final, partial);
  assert.equal(merged.turns[0].answer, "Keep the route clear.");
  // Nor can it overwrite a manual retry's newer queued state.
  const retried = conversation(turn(7, { status: "queued", partial: "" }));
  assert.equal(mergeConversation(retried, partial).turns[0].status, "queued");
});

test("new turns and conversation-level limits come from the latest read", () => {
  const current = conversation(turn(2));
  const incoming = {
    ...conversation(turn(2), { ...turn(1, { status: "queued" }), id: "t2" }),
    blocked_reason: "Limit reached",
  };
  const merged = mergeConversation(current, incoming);
  assert.deepEqual(
    merged.turns.map((t) => t.id),
    ["t1", "t2"],
  );
  assert.equal(merged.blocked_reason, "Limit reached");
  assert.equal(mergeConversation(undefined, incoming), incoming);
});

test("active and incomplete states are explicit", () => {
  assert.equal(isActive(turn(1, { status: "queued" })), true);
  assert.equal(isActive(turn(1, { status: "running" })), true);
  assert.equal(isActive(turn(1, { status: "failed" })), false);
  assert.equal(
    isIncomplete(turn(1, { status: "failed", partial: "Half" })),
    true,
  );
  assert.equal(isIncomplete(turn(1, { status: "failed", partial: "" })), false);
  assert.equal(
    isIncomplete(turn(1, { status: "complete", answer: "Done" })),
    false,
  );
});
