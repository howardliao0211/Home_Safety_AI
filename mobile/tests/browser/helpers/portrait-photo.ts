import { expect, type Page } from "@playwright/test";
import type { AppState } from "../../../src/domain/model";

/** Retained portrait drafts remain supported without offering a third sample. */
export async function restorePortraitDraft(page: Page) {
  await expect(
    page.getByRole("button", { name: /^Use .+ sample$/ }),
  ).toHaveCount(2);
  await page.getByRole("button", { name: "Use living room sample" }).click();
  await expect(
    page.getByRole("img", { name: "Living room sample" }),
  ).toBeVisible();
  await page.evaluate(async () => {
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open("home-safety-preview", 1);
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const db = request.result;
        const tx = db.transaction("preview", "readwrite");
        const store = tx.objectStore("preview");
        const read = store.get("state");
        read.onsuccess = () => {
          const state = read.result as AppState;
          state.draft!.photo = {
            id: "retained-portrait-photo",
            label: "Portrait room sample",
            sample: "portrait",
          };
          store.put(state, "state");
        };
        tx.oncomplete = () => {
          db.close();
          resolve();
        };
        tx.onerror = () => {
          db.close();
          reject(tx.error);
        };
        tx.onabort = () => {
          db.close();
          reject(tx.error);
        };
      };
    });
  });
  await page.reload();
  await expect(
    page.getByRole("img", { name: "Portrait room sample" }),
  ).toBeVisible();
}
