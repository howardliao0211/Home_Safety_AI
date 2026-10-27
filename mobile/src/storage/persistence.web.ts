import type { AppState } from "../domain/model";
import { stateKey } from "../api/config";

// IndexedDB retains selected image data across reloads without localStorage's
// small synchronous quota. Metadata and photos commit in one transaction.
let database: Promise<IDBDatabase> | undefined;
function open() {
  if (!database)
    database = new Promise((resolve, reject) => {
      const request = indexedDB.open("home-safety-preview", 1);
      request.onupgradeneeded = () =>
        request.result.createObjectStore("preview");
      request.onsuccess = () => resolve(request.result);
      request.onerror = () =>
        reject(request.error ?? new Error("Browser storage is unavailable."));
      request.onblocked = () =>
        reject(new Error("Close other preview tabs to open local storage."));
    });
  database = database.catch((error) => {
    database = undefined;
    throw error;
  });
  return database;
}
export const persistence = {
  async load(): Promise<AppState | null> {
    const db = await open();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction("preview", "readonly");
      const request = transaction.objectStore("preview").get(stateKey);
      transaction.oncomplete = () => resolve(request.result ?? null);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () =>
        reject(
          transaction.error ?? new Error("Reading local data was interrupted."),
        );
    });
  },
  async save(state: AppState): Promise<void> {
    const db = await open();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction("preview", "readwrite");
      transaction.objectStore("preview").put(state, stateKey);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () =>
        reject(
          transaction.error ?? new Error("Saving local data was interrupted."),
        );
    });
  },
};
