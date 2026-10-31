import assert from "node:assert/strict";
import { test } from "node:test";
import {
  emptyConversation,
  isActive,
  isIncomplete,
  mergeConversation,
  observeJob,
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

test("observation reads start on a fixed cadence, never overlap and survive failed reads", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "Date"] });
  const starts: number[] = [];
  const latency = [100, 400, 50, 50];
  let call = 0;
  const read = () => {
    starts.push(Date.now());
    const index = call++;
    return new Promise<void>((resolve, reject) =>
      setTimeout(
        () => (index === 2 ? reject(new Error("offline")) : resolve()),
        latency[index] ?? 50,
      ),
    );
  };
  const stop = observeJob(read, 250);
  const advance = async (ms: number) => {
    for (let i = 0; i < ms; i++) {
      t.mock.timers.tick(1);
      await Promise.resolve();
      await Promise.resolve();
    }
  };
  await advance(1100);
  stop();
  await advance(1000);
  // 0 → 250 on cadence; the 400 ms read delays the next start to 650 with no
  // overlap; a failed read (connection loss) keeps observing; stop ends it.
  assert.deepEqual(starts, [0, 250, 650, 900]);
});
