import assert from "node:assert/strict";
import test from "node:test";
import { secureStorage } from "../src/auth/secure-storage";
import { StateStore } from "../src/storage/state-store";

test("secure session restores a large Firebase record and failed replacement preserves the committed session", async () => {
  const records = new Map<string, string>();
  let fail = false;
  let nonce = 0;
  const adapter = {
    getItem: async (key: string) => records.get(key) ?? null,
    setItem: async (key: string, value: string) => {
      assert.match(key, /^[a-zA-Z0-9._-]+$/);
      assert.ok(Buffer.byteLength(value) < 2048);
      if (fail && key.endsWith("-1")) throw new Error("storage interrupted");
      records.set(key, value);
    },
    removeItem: async (key: string) => {
      records.delete(key);
    },
  };
  const storage = secureStorage(adapter, () => String(++nonce));
  const value = JSON.stringify({
    uid: "account:A",
    token: "private".repeat(1400),
  });
  await storage.setItem("firebase:authUser:[DEFAULT]", value);
  assert.equal(
    await secureStorage(adapter, () => "restart").getItem(
      "firebase:authUser:[DEFAULT]",
    ),
    value,
  );
  fail = true;
  await assert.rejects(
    storage.setItem("firebase:authUser:[DEFAULT]", "replacement".repeat(300)),
  );
  assert.equal(await storage.getItem("firebase:authUser:[DEFAULT]"), value);
  fail = false;
  await storage.removeItem("firebase:authUser:[DEFAULT]");
  assert.equal(records.size, 0);
});

test("disposed account state cannot publish queued or late changes to the next session", async () => {
  let publications = 0;
  let writes = 0;
  const store = new StateStore(
    {
      load: async () => null,
      save: async () => {
        writes++;
      },
    },
    () => {
      publications++;
    },
  );
  await store.load();
  const pending = store.update((state) => ({
    ...state,
    draft: { profiles: [], scenario: "hazards" },
  }));
  store.dispose();
  await assert.rejects(pending, /session has changed/);
  await store.drained();
  assert.equal(publications, 1);
  assert.equal(writes, 1);
});

test("logout drains the initial cache save before clearing account storage", async () => {
  let release!: () => void;
  let saving!: () => void;
  const started = new Promise<void>((resolve) => {
    saving = resolve;
  });
  const store = new StateStore({
    load: async () => null,
    save: async () => {
      saving();
      await new Promise<void>((resolve) => {
        release = resolve;
      });
    },
  });
  const loading = store.load();
  await started;
  store.dispose();
  let drained = false;
  const cleanup = store.drained().then(() => {
    drained = true;
  });
  await new Promise((resolve) => setImmediate(resolve));
  try {
    assert.equal(drained, false);
  } finally {
    release();
    await assert.rejects(loading, /session has changed/);
    await cleanup;
  }
});
