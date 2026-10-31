import {
  expect,
  test,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import path from "node:path";

const backend = "http://127.0.0.1:8001";
async function session(page: Page) {
  return page.evaluate(() => {
    const key = Object.keys(sessionStorage).find((key) =>
      key.startsWith("firebase:authUser:"),
    );
    return key ? JSON.parse(sessionStorage.getItem(key)!) : null;
  });
}
async function deviceId(page: Page) {
  return (await session(page))?.uid;
}
async function bearer(page: Page) {
  return "Bearer " + (await session(page))?.stsTokenManager.accessToken;
}
async function serverAssessment(page: Page, request: APIRequestContext) {
  const response = await request.get(backend + "/v1/assessments/latest", {
    headers: {
      Authorization: await bearer(page),
      "X-Device-ID": await deviceId(page),
    },
  });
  expect(response.status()).toBe(200);
  return response.json();
}
async function submit(page: Page) {
  await page.getByRole("button", { name: "Review photo", exact: true }).click();
  await page
    .getByRole("button", { name: "Create assessment", exact: true })
    .click();
}
async function start(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Assess a room", exact: true })
    .click();
}
test.beforeEach(async ({ page, request }) => {
  const email = `${crypto.randomUUID()}@example.test`;
  const endpoint = "http://127.0.0.1:9099/identitytoolkit.googleapis.com/v1/";
  const signed = await request.post(endpoint + "accounts:signUp?key=local", {
    data: { email, password: "Strong-password-123", returnSecureToken: true },
  });
  const user = await signed.json();
  const verified = await request.post(
    endpoint + "projects/home-safety-local/accounts:update",
    {
      headers: { Authorization: "Bearer owner" },
      data: { localId: user.localId, emailVerified: true },
    },
  );
  expect(verified.ok()).toBeTruthy();
  await page.goto("/");
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(email);
  await page
    .getByLabel("Password", { exact: true })
    .fill("Strong-password-123");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Assess a room", exact: true }),
  ).toBeVisible();
  await request.post(backend + "/__test/control", {
    data: { fail_initial: 0, fail_revision: 0 },
  });
});
test.afterEach(async ({ page, request }) => {
  if (!(await session(page))) return;
  const headers = { Authorization: await bearer(page) };
  for (let i = 0; i < 5; i += 1) {
    const latest = await request.get(backend + "/v1/assessments/latest", {
      headers,
    });
    if (latest.status() === 404) break;
    if (!latest.ok()) break;
    await request.delete(
      backend + "/v1/assessments/" + (await latest.json()).id,
      { headers },
    );
  }
});

test("connected lifecycle: upload, retained failures, retry, cache-free restore, status, persistent finding chat and deletion", async ({
  page,
  request,
}) => {
  await request.post(backend + "/__test/control", {
    data: { fail_initial: 1, fail_chat: 1 },
  });
  let uploads = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url() === backend + "/v1/assessments")
      uploads += 1;
  });
  await start(page);
  await expect(
    page.getByText("INTERACTIVE PREVIEW", { exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Use living room sample" }).click();
  await page.getByRole("checkbox", { name: "Baby", exact: true }).click();
  await page.getByRole("checkbox", { name: "Pet", exact: true }).click();
  await submit(page);
  await expect(
    page.getByRole("button", { name: "Retry analysis" }),
  ).toBeVisible();
  const failed = await serverAssessment(page, request);
  expect(failed.status).toBe("failed");
  expect(failed.photo.uploaded).toBe(true);
  expect(failed.profiles).toEqual(["Baby", "Pet"]);
  await page.reload();
  await page.getByRole("button", { name: "Retry analysis" }).click();
  await expect(page.getByText("0 of 2 handled", { exact: true })).toBeVisible();
  expect(uploads).toBe(1);
  const assessmentId = (await serverAssessment(page, request)).id;
  expect(assessmentId).toBe(failed.id);
  const identity = await deviceId(page);
  await page.evaluate(async () => {
    const db = await new Promise<IDBDatabase>((resolve) => {
      const open = indexedDB.open("home-safety-preview", 1);
      open.onsuccess = () => resolve(open.result);
    });
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction("preview", "readwrite");
      tx.objectStore("preview").clear();
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    db.close();
  });
  await page.goto("/");
  await page.getByRole("button", { name: /^Open / }).click();
  await expect(page.getByText("0 of 2 handled", { exact: true })).toBeVisible();
  expect(await deviceId(page)).toBe(identity);
  await expect(
    page.getByRole("img", { name: "Your saved room photo", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Photo unavailable", { exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("checkbox", {
      name: "Mark resolved: Check the cabinet",
      exact: true,
    })
    .click();
  await expect(page.getByText("1 of 2 handled", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "View Keep the walkway clear", exact: true })
    .click();
  await expect(page).toHaveURL(/\/finding\//);
  const findingUrl = page.url();
  await expect(
    page.getByRole("button", { name: "Ask AI to check", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Chat about it", exact: true })
    .click();
  // The server accepts and queues the turn, but the response is lost in transport.
  await page.route("**/chat/turns", async (route) => {
    await route.fetch();
    await route.abort("failed");
    await page.unroute("**/chat/turns");
  });
  await page
    .getByRole("textbox", { name: "Your question", exact: true })
    .fill("How does this affect night use?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  // The durable job still runs; its partial text arrives before it fails.
  await expect(page.getByText("Writing…", { exact: true })).toBeVisible();
  await expect(
    page
      .getByText(/^Keep the route/)
      .locator("visible=true")
      .first(),
  ).toBeVisible();
  await expect(
    page.getByText("INCOMPLETE RESPONSE", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "Your question", exact: true }),
  ).toHaveValue("");
  await page.reload();
  await expect(
    page.getByText("INCOMPLETE RESPONSE", { exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId("chat-user-message")).toHaveCount(1);
  // The retry is queued even if its response is lost, then replaces the partial.
  await page.route("**/chat/turns/*/generate", async (route) => {
    await route.fetch();
    await route.abort("failed");
    await page.unroute("**/chat/turns/*/generate");
  });
  await page.getByRole("button", { name: "Retry reply", exact: true }).click();
  await expect(
    page.getByText("Keep the route clear; only you decide its status.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("INCOMPLETE RESPONSE", { exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("textbox", { name: "Your question", exact: true })
    .fill("Does that also apply during the day?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(
    page.getByText(
      "Our earlier discussion is included. Keep the route clear; only you decide its status.",
      { exact: true },
    ),
  ).toBeVisible();
  const stored = await serverAssessment(page, request);
  const walkway = stored.findings.find(
    (f: { title: string }) => f.title === "Keep the walkway clear",
  );
  expect(walkway.status).toBe("open");
  expect(walkway.submissions).toHaveLength(0);
  const chatPath =
    backend + `/v1/assessments/${assessmentId}/findings/${walkway.id}/chat`;
  const conversation = await (
    await request.get(chatPath, {
      headers: { Authorization: await bearer(page) },
    })
  ).json();
  expect(conversation.turns).toHaveLength(2);
  expect(
    conversation.turns.every(
      (t: { status: string }) => t.status === "complete",
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "Back to finding", exact: true })
    .click();
  await expect(page).toHaveURL(findingUrl);
  await page
    .getByRole("button", { name: "Back to checklist", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Delete assessment", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Delete assessment and photos", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Assess a room", exact: true }),
  ).toBeVisible();
  const headers = {
    Authorization: await bearer(page),
    "X-Device-ID": identity,
  };
  expect(
    (
      await request.get(backend + "/v1/assessments/" + assessmentId, {
        headers,
      })
    ).status(),
  ).toBe(404);
  expect(
    (
      await request.get(
        backend + `/v1/assessments/${assessmentId}/photos/${stored.photo.id}`,
        { headers },
      )
    ).status(),
  ).toBe(404);
});

test("network failures retain the session and retry without preview fallback", async ({
  page,
}) => {
  const identity = await deviceId(page);
  await page.route(backend + "/v1/assessments", (route) => route.abort());
  await page.reload();
  await expect(
    page
      .getByText(/Could not reach the assessment service/)
      .filter({ visible: true }),
  ).toBeVisible();
  await expect(
    page.getByText("INTERACTIVE PREVIEW", { exact: true }),
  ).toHaveCount(0);
  await page.unroute(backend + "/v1/assessments");
  await page.getByRole("button", { name: "Retry loading history" }).click();
  await expect(
    page.getByRole("button", { name: "Assess a room", exact: true }),
  ).toBeVisible();
  expect(await deviceId(page)).toBe(identity);
});

test("sign-out during analysis discards the late response before another account opens", async ({
  page,
  request,
}) => {
  const ownerToken = await bearer(page);
  let delivered = false;
  let release!: () => void;
  let assessmentId = "";
  const delayed = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(backend + "/v1/assessments/*/analyze", async (route) => {
    const response = await route.fetch();
    assessmentId = (await response.json()).id;
    delivered = true;
    await delayed;
    await route.fulfill({ response }).catch(() => {});
  });
  await start(page);
  await page.getByRole("button", { name: "Use living room sample" }).click();
  await submit(page);
  await expect.poll(() => delivered).toBe(true);
  await page.getByRole("button", { name: "Account", exact: true }).click();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Sign in", exact: true }),
  ).toBeVisible();
  release();
  const endpoint = "http://127.0.0.1:9099/identitytoolkit.googleapis.com/v1/";
  const email = `${crypto.randomUUID()}@example.test`;
  const registered = await (
    await request.post(endpoint + "accounts:signUp?key=local", {
      data: { email, password: "Strong-password-123", returnSecureToken: true },
    })
  ).json();
  await request.post(endpoint + "projects/home-safety-local/accounts:update", {
    headers: { Authorization: "Bearer owner" },
    data: { localId: registered.localId, emailVerified: true },
  });
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(email);
  await page
    .getByLabel("Password", { exact: true })
    .fill("Strong-password-123");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Assess a room", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("0 of 2 handled", { exact: true })).toHaveCount(
    0,
  );
  await expect(page.getByRole("img", { name: /room photo/ })).toHaveCount(0);
  await request.delete(backend + "/v1/assessments/" + assessmentId, {
    headers: { Authorization: ownerToken },
  });
});

test("real file upload, failed status write, server restart state and history restoration after deletion", async ({
  page,
  request,
}) => {
  await start(page);
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Choose photo", exact: true }).click();
  await (
    await chooser
  ).setFiles(path.join(process.cwd(), "assets/rooms/living-room.jpg"));
  await submit(page);
  await expect(page.getByText("0 of 2 handled", { exact: true })).toBeVisible();
  const first = await serverAssessment(page, request);
  await page.route(backend + "/v1/assessments/**/findings/*", (route) =>
    route.request().method() === "PATCH" ? route.abort() : route.continue(),
  );
  await page
    .getByRole("checkbox", {
      name: "Mark resolved: Check the cabinet",
      exact: true,
    })
    .click();
  await expect(
    page
      .getByText(/Could not reach the assessment service/)
      .filter({ visible: true }),
  ).toBeVisible();
  await expect(page.getByText("0 of 2 handled", { exact: true })).toBeVisible();
  expect(
    (await serverAssessment(page, request)).findings.every(
      (f: { status: string }) => f.status === "open",
    ),
  ).toBe(true);
  await page.unroute(backend + "/v1/assessments/**/findings/*");
  await page
    .getByRole("checkbox", {
      name: "Mark resolved: Check the cabinet",
      exact: true,
    })
    .click();
  await expect(page.getByText("1 of 2 handled", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("1 of 2 handled", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "New assessment", exact: true })
    .click();
  await page.getByRole("button", { name: "Use quiet room sample" }).click();
  await submit(page);
  await expect(page.getByText("0 of 2 handled", { exact: true })).toBeVisible();
  const second = await serverAssessment(page, request);
  expect(second.id).not.toBe(first.id);
  await page
    .getByRole("button", { name: "Delete assessment", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Delete assessment and photos", exact: true })
    .click();
  await expect(page).toHaveURL(/\/$/);
  await page.getByRole("button", { name: /^Open / }).click();
  await expect(page).toHaveURL(new RegExp(`/assessment/${first.id}$`));
  await expect(page.getByText("1 of 2 handled", { exact: true })).toBeVisible();
});

test("eager finding highlights are only fetched, align inline, hide and report independently of checklist status", async ({
  page,
  request,
}) => {
  let posts = 0;
  let reads = 0;
  let reported = false;
  let annotationState = "queued";
  let maskOffline = true;
  let delayNextRead = false;
  let pendingRead = false;
  let releaseRead: () => void = () => {};
  const job = async (id: string) => {
    const saved = await serverAssessment(page, request);
    return {
      id,
      revision: "initial",
      attempt: posts + 1,
      photo_id: saved.photo.id,
      photo_kind: "original",
      // Real attempts carry the stored photo's size; mismatches are not drawn.
      width: 1200,
      height: 900,
      orientation: 1,
      retryable: true,
    };
  };
  await page.route("**/findings/*/annotations**", async (route) => {
    const url = route.request().url();
    const method = route.request().method();
    if (url.endsWith("/mask")) {
      if (maskOffline) {
        await route.abort();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==",
          "base64",
        ),
      });
      return;
    }
    const id = url.endsWith("/annotations")
      ? "retried-annotation"
      : url.split("/annotations/")[1].split("/")[0];
    if (delayNextRead && method === "GET") {
      delayNextRead = false;
      pendingRead = true;
      await new Promise<void>((resolve) => {
        releaseRead = resolve;
      });
      await route.fulfill({
        status: 200,
        json: { ...(await job(id)), state: "ready" },
      });
      return;
    }
    if (url.endsWith("/feedback")) {
      reported = true;
      annotationState = "reported";
    }
    if (method === "GET") reads++;
    if (method === "POST" && url.endsWith("/annotations")) {
      posts++;
      expect(route.request().postDataJSON()).toEqual({
        revision: "initial",
        retry: true,
      });
      annotationState = "queued";
    }
    await route.fulfill({
      status: annotationState === "queued" ? 202 : 200,
      json: {
        ...(await job(id)),
        state: annotationState,
        reason: reported ? "You reported the wrong object." : null,
      },
    });
  });
  await start(page);
  await page.getByRole("button", { name: "Use living room sample" }).click();
  await submit(page);
  await expect(page.getByText("0 of 2 handled", { exact: true })).toBeVisible();
  // The completed assessment already lists each finding's highlight attempt.
  const saved = await serverAssessment(page, request);
  expect(
    saved.findings.every(
      (f: { annotation: { id: string } }) => f.annotation.id,
    ),
  ).toBe(true);
  expect(posts + reads).toBe(0);
  await page.getByRole("button", { name: /Check the cabinet/ }).click();
  await expect(
    page.getByText("Highlight queued…", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("A cable is visible across the walking route.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Mark resolved", exact: true }),
  ).toBeEnabled();
  annotationState = "ready";
  const highlight = page.getByRole("img", {
    name: "AI-generated highlight",
    exact: true,
  });
  await expect(
    page.getByRole("button", { name: "Reload highlight", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Retry highlight", exact: true }),
  ).toHaveCount(0);
  maskOffline = false;
  await expect(highlight).toBeVisible();
  await expect(
    page.getByText(/^AI-generated highlight · may mark the wrong object/),
  ).toBeVisible();
  expect(posts).toBe(0);
  // Terminal state stops polling.
  const settled = reads;
  await page.waitForTimeout(2500);
  expect(reads).toBe(settled);
  await page
    .getByRole("button", { name: "Hide highlights", exact: true })
    .click();
  await expect(highlight).toHaveCount(0);
  await page
    .getByRole("button", { name: "Show highlights", exact: true })
    .click();
  await expect(highlight).toBeVisible();
  // Inline evidence keeps photo and mask on one canvas; zoom is gone.
  await expect(page.getByRole("button", { name: /Zoom/ })).toHaveCount(0);
  const maskBox = await highlight.boundingBox();
  const imageBox = await page
    .getByRole("img", { name: "Original evidence photo", exact: true })
    .boundingBox();
  expect(maskBox).toEqual(imageBox);
  // The full photo keeps its own aspect ratio inline (no cropping).
  const natural = await page
    .getByRole("img", { name: "Original evidence photo", exact: true })
    .evaluate(async (node) => {
      // expo-image renders either an <img> or a background image on web.
      const element = [node, ...node.querySelectorAll("*")].find(
        (child) =>
          child instanceof HTMLImageElement ||
          getComputedStyle(child).backgroundImage.startsWith("url("),
      ) as HTMLElement;
      const source =
        element instanceof HTMLImageElement
          ? element.src
          : getComputedStyle(element).backgroundImage.slice(5, -2);
      const image = new Image();
      image.src = source;
      await image.decode();
      return image.naturalWidth / image.naturalHeight;
    });
  expect(imageBox!.width / imageBox!.height).toBeCloseTo(natural, 1);
  delayNextRead = true;
  await page.evaluate(() =>
    document.dispatchEvent(new Event("visibilitychange")),
  );
  await expect.poll(() => pendingRead).toBe(true);

  await page
    .getByRole("button", { name: "Wrong object highlighted", exact: true })
    .click();
  await expect(
    page.getByText("You reported the wrong object.", { exact: true }),
  ).toBeVisible();
  expect(reported).toBe(true);
  const oldRead = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      /\/annotations\/[^/]+$/.test(response.url()),
  );
  releaseRead();
  await oldRead;
  await page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );
  await expect(
    page.getByText("You reported the wrong object.", { exact: true }),
  ).toBeVisible();

  await expect(highlight).toHaveCount(0);
  expect(
    (await serverAssessment(page, request)).findings.every(
      (f: { status: string }) => f.status === "open",
    ),
  ).toBe(true);
  // Restarting only fetches the saved attempt.
  await page.reload();
  await expect(
    page.getByText("You reported the wrong object.", { exact: true }),
  ).toBeVisible();
  await expect(highlight).toHaveCount(0);
  expect(posts).toBe(0);
  await page
    .getByRole("button", { name: "Retry highlight", exact: true })
    .click();
  await expect(
    page.getByText("Highlight queued…", { exact: true }),
  ).toBeVisible();
  expect(posts).toBe(1);
});
