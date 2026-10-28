// Firebase's public React Native persistence adapter accepts this storage interface.
// Keep complete SDK session records in encrypted storage; never assessment storage.
export interface SecretStorage {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  removeItem(key: string): Promise<void>;
}
export function secureStorage(
  store: SecretStorage,
  nonce: () => string,
): SecretStorage {
  let queue: Promise<unknown> = Promise.resolve();
  const keyFor = (key: string) =>
    "firebase-" +
    Array.from(key)
      .map((c) => c.codePointAt(0)!.toString(16))
      .join("-");
  const serial = <T>(work: () => Promise<T>): Promise<T> => {
    const result = queue.then(work);
    queue = result.catch(() => {});
    return result;
  };
  async function manifest(
    key: string,
  ): Promise<{ id: string; count: number } | null> {
    const value = await store.getItem(key);
    return value ? JSON.parse(value) : null;
  }
  async function removeChunks(
    key: string,
    old: { id: string; count: number } | null,
  ) {
    if (old)
      for (let i = 0; i < old.count; i++)
        await store.removeItem(`${key}-${old.id}-${i}`);
  }
  return {
    getItem: (raw) =>
      serial(async () => {
        const key = keyFor(raw),
          record = await manifest(key);
        if (!record) return null;
        let value = "";
        for (let i = 0; i < record.count; i++) {
          const chunk = await store.getItem(`${key}-${record.id}-${i}`);
          if (chunk === null)
            throw new Error(
              "Secure session storage is incomplete. Sign in again.",
            );
          value += chunk;
        }
        return value;
      }),
    setItem: (raw, value) =>
      serial(async () => {
        const key = keyFor(raw),
          old = await manifest(key);
        const characters = Array.from(value);
        const record = {
          id: nonce(),
          count: Math.ceil(characters.length / 400),
        };
        // Each chunk is at most 1600 UTF-8 bytes. Commit the manifest last.
        try {
          for (let i = 0; i < record.count; i++)
            await store.setItem(
              `${key}-${record.id}-${i}`,
              characters.slice(i * 400, (i + 1) * 400).join(""),
            );
          await store.setItem(key, JSON.stringify(record));
        } catch (error) {
          await removeChunks(key, record).catch(() => {});
          throw error;
        }
        await removeChunks(key, old);
      }),
    removeItem: (raw) =>
      serial(async () => {
        const key = keyFor(raw),
          old = await manifest(key);
        await store.removeItem(key);
        await removeChunks(key, old);
      }),
  };
}
