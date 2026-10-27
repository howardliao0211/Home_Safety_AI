import {
  expect,
  test,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import path from "node:path";

const backend = "http://127.0.0.1:8001";
const token = "browser-integration-token";
async function deviceId(page: Page) {
  return (await page.evaluate(() =>
    localStorage.getItem("home-safety-device-id-v1"),
  ))!;
}
async function serverAssessment(page: Page, request: APIRequestContext) {
  const response = await request.get(backend + "/v1/assessments/latest", {
    headers: {
      Authorization: `Bearer ${token}`,
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
    .getByRole("button", { name: "Start with a room", exact: true })
    .click();
}
test.beforeEach(async ({ request }) => {
  await request.post(backend + "/__test/control", {
    data: { fail_initial: 0, fail_revision: 0 },
  });
});
test.afterEach(async ({ page, request }) => {
  const device = await page
    .evaluate(() => localStorage.getItem("home-safety-device-id-v1"))
    .catch(() => null);
  if (!device) return;
  const headers = { Authorization: `Bearer ${token}`, "X-Device-ID": device };
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

test("connected lifecycle: upload, retained failures, retry, cache-free restore, status, follow-up, review and deletion", async ({
  page,
  request,
}) => {
  await request.post(backend + "/__test/control", {
    data: { fail_initial: 1, fail_revision: 1 },
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
      tx.objectStore("preview").delete("state-api-v1:http://127.0.0.1:8001");
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    db.close();
  });
  await page.goto("/");
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
  await page
    .getByRole("button", { name: "Answer a question", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Your answer", exact: true })
    .fill("Yes, we use it at night.");
  await page
    .getByRole("button", { name: "Submit follow-up", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Retry check", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "Your answer", exact: true }),
  ).toBeDisabled();
  await page.reload();
  await expect(
    page.getByRole("textbox", { name: "Your answer", exact: true }),
  ).toHaveValue("Yes, we use it at night.");
  await page.getByRole("button", { name: "Retry check", exact: true }).click();
  await expect(page.getByText(/Follow-up received/)).toBeVisible();
  await expect(
    page.getByText("Additional evidence was considered in this linked check.", {
      exact: true,
    }),
  ).toBeVisible();
  let stored = await serverAssessment(page, request);
  const walkway = stored.findings.find(
    (f: { title: string }) => f.title === "Keep the walkway clear",
  );
  expect(walkway.status).toBe("open");
  expect(walkway.submissions).toHaveLength(1);
  expect(walkway.submissions[0].attempts).toBe(2);
  await page.getByRole("button", { name: "Back to checklist" }).click();
  await page
    .getByRole("button", { name: "View Check the cabinet", exact: true })
    .click();
  await page.getByRole("button", { name: "Skip for now", exact: true }).click();
  await expect(page.getByText(/You skipped this request/)).toBeVisible();
  await page
    .getByRole("button", { name: "Ask AI to check", exact: true })
    .click();
  await page.getByRole("button", { name: "Use quiet room sample" }).click();
  await page
    .getByRole("button", { name: "Request photo review", exact: true })
    .click();
  await expect(
    page.getByText("Review received", { exact: true }),
  ).toBeVisible();
  stored = await serverAssessment(page, request);
  const cabinet = stored.findings.find(
    (f: { title: string }) => f.title === "Check the cabinet",
  );
  expect(cabinet.status).toBe("resolved");
  expect(cabinet.follow_up.state).toBe("skipped");
  expect(cabinet.submissions[0].photo.uploaded).toBe(true);
  await page.getByRole("button", { name: "Return to finding" }).click();
  await page.getByRole("button", { name: "Back to checklist" }).click();
  await page
    .getByRole("button", { name: "Delete assessment", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Delete assessment and photos", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Start with a room", exact: true }),
  ).toBeVisible();
  const headers = { Authorization: `Bearer ${token}`, "X-Device-ID": identity };
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

test("connection/auth failures stay visible and never become preview results", async ({
  page,
}) => {
  await page.route(backend + "/v1/assessments/latest", (route) =>
    route.fulfill({
      status: 401,
      headers: { "Access-Control-Allow-Origin": "http://127.0.0.1:8082" },
      json: {
        error: {
          message: "The demo token was rejected.",
          code: "unauthorized",
        },
      },
    }),
  );
  await page.goto("/");
  await expect(
    page.getByText("The demo token was rejected.", { exact: true }),
  ).toBeVisible();
  const identity = await deviceId(page);
  await page.unroute(backend + "/v1/assessments/latest");
  await page.getByRole("button", { name: "Retry connecting" }).click();
  await expect(
    page.getByRole("button", { name: "Start with a room", exact: true }),
  ).toBeVisible();
  await page.route(backend + "/v1/assessments/latest", (route) =>
    route.abort(),
  );
  await page.reload();
  await expect(
    page.getByText(/Could not reach the assessment service/),
  ).toBeVisible();
  await expect(
    page.getByText("INTERACTIVE PREVIEW", { exact: true }),
  ).toHaveCount(0);
  await page.unroute(backend + "/v1/assessments/latest");
  await page.getByRole("button", { name: "Retry connecting" }).click();
  await expect(
    page.getByRole("button", { name: "Start with a room", exact: true }),
  ).toBeVisible();
  expect(await deviceId(page)).toBe(identity);
});

test("real file upload, failed status write, server restart state and latest restoration after deletion", async ({
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
    page.getByText(/Could not reach the assessment service/),
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
  await expect(page).toHaveURL(new RegExp(`/assessment/${first.id}$`));
  await expect(page.getByText("1 of 2 handled", { exact: true })).toBeVisible();
});
