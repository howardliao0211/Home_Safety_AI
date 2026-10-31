import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

async function start(page: Page, scenario?: string) {
  await page.goto("/");
  if (scenario) {
    await page
      .getByRole("button", { name: "Preview tools", exact: true })
      .click();
    await page.getByRole("radio", { name: scenario, exact: true }).click();
    await page.getByRole("button", { name: "Start fresh demo" }).click();
  } else await page.getByRole("button", { name: "Assess a room" }).click();
  await expect(
    page.getByRole("button", { name: "Review photo", exact: true }),
  ).toBeVisible();
}
async function submitRoom(page: Page) {
  await page.getByRole("button", { name: "Review photo", exact: true }).click();
  await page.getByRole("button", { name: "Create sample assessment" }).click();
}
async function sampleAssessment(page: Page, scenario?: string) {
  await start(page, scenario);
  await page.getByRole("button", { name: "Use living room sample" }).click();
  await submitRoom(page);
  await expect(
    page.getByRole("button", { name: "New assessment", exact: true }),
  ).toBeVisible();
}

test("household journey: profiles, checklist actions, dismissal, persistence and finding chat", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await start(page);
  await page.getByRole("button", { name: "Use living room sample" }).click();
  await page.getByRole("checkbox", { name: "Baby", exact: true }).click();
  await page.getByRole("checkbox", { name: "Pet", exact: true }).click();
  await submitRoom(page);
  await expect(page.getByText("0 of 3 handled", { exact: true })).toBeVisible();
  await expect(page.getByText(/Baby · Pet/)).toBeVisible();
  const assessmentUrl = page.url();
  await page
    .getByRole("checkbox", {
      name: "Mark resolved: Check the tall cabinet",
      exact: true,
    })
    .click();
  await expect(page.getByText("1 of 3 handled", { exact: true })).toBeVisible();
  await page
    .getByRole("button", {
      name: "View Put small items out of reach",
      exact: true,
    })
    .click();
  await page.getByRole("button", { name: "Dismiss as not relevant" }).click();
  await page
    .getByRole("textbox", { name: "Dismissal note (optional)" })
    .fill("Stored out of reach.");
  await page.getByRole("button", { name: "Save dismissal" }).click();
  await expect(page.getByText("Your note: Stored out of reach.")).toBeVisible();
  await page.getByRole("button", { name: "Back to checklist" }).click();
  await expect(
    page.getByText("1 open · 1 resolved · 1 dismissed", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("1 open · 1 resolved · 1 dismissed", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "View Give the walkway more room" })
    .click();
  await page
    .getByRole("button", { name: "Chat about it", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Your question", exact: true })
    .fill("How can I reduce trips at night?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByText(/Simulated guidance about/)).toBeVisible();
  await page
    .getByRole("button", { name: "Back to finding", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Mark resolved", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Back to checklist" }).click();
  await expect(page).toHaveURL(assessmentUrl);
  await expect(
    page.getByText("1 open · 1 resolved · 1 dismissed", { exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("analysis failure keeps input and succeeds with manual retry", async ({
  page,
}) => {
  await start(page, "Analysis retry");
  await page.getByRole("button", { name: "Use quiet room sample" }).click();
  await submitRoom(page);
  await expect(
    page.getByRole("button", { name: "Retry analysis" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Retry analysis" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Retry analysis" }).click();
  await expect(page.getByText("0 of 3 handled", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /^View / })).toHaveCount(3);
});

test("a finding without a follow-up keeps chat available after dismissal", async ({
  page,
}) => {
  await sampleAssessment(page);
  await page
    .getByRole("button", {
      name: "View Put small items out of reach",
      exact: true,
    })
    .click();
  await page
    .getByRole("button", { name: "Dismiss as not relevant", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Save dismissal", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Skip for now", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Chat about it", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Your question", exact: true })
    .fill("What if my household changes?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByText(/Simulated guidance about/)).toBeVisible();
  await page
    .getByRole("button", { name: "Back to finding", exact: true })
    .click();
  await expect(page.getByText(/Dismissed by you/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Reopen finding", exact: true }),
  ).toBeVisible();
});

test("new draft cancellation retains the previous assessment; deletion returns Home with earlier data", async ({
  page,
}) => {
  await sampleAssessment(page);
  const first = page.url();
  await page
    .getByRole("button", { name: "New assessment", exact: true })
    .click();
  await page.getByRole("button", { name: "Use quiet room sample" }).click();
  await page.getByRole("button", { name: "Cancel new assessment" }).click();
  await page.getByRole("button", { name: "Keep it", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Review photo" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Cancel new assessment" }).click();
  await page.getByRole("button", { name: "Discard draft" }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.getByRole("button", { name: /^Open Living Room Review/ }).click();
  await expect(page).toHaveURL(first);
  await page
    .getByRole("button", { name: "New assessment", exact: true })
    .click();
  await page.getByRole("button", { name: "Use quiet room sample" }).click();
  await submitRoom(page);
  await expect(
    page.getByRole("button", { name: "Delete assessment", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Delete assessment", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Delete assessment and photos" })
    .click();
  await expect(page).toHaveURL(/\/$/);
  await page.getByRole("button", { name: /^Open Living Room Review/ }).click();
  await expect(page).toHaveURL(first);
  await page
    .getByRole("button", { name: "Delete assessment", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Delete assessment and photos" })
    .click();
  await expect(
    page.getByRole("button", { name: "Assess a room" }),
  ).toBeVisible();
});

test("actual browser upload persists across reload and deletion removes retained data", async ({
  page,
}) => {
  await start(page);
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Choose photo", exact: true }).click();
  await (await chooser).setFiles(path.resolve("assets/rooms/living-room.jpg"));
  await expect(
    page.getByRole("button", { name: "Review photo", exact: true }),
  ).toBeEnabled();
  await submitRoom(page);
  await expect(
    page.getByRole("button", { name: "New assessment", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("living-room.jpg", { exact: true }),
  ).toBeVisible();
  const photo = await page.evaluate(async () => {
    const open = indexedDB.open("home-safety-preview");
    const db = await new Promise<IDBDatabase>((r) => {
      open.onsuccess = () => r(open.result);
    });
    const request = db
      .transaction("preview")
      .objectStore("preview")
      .get("state");
    const saved = await new Promise<any>((r) => {
      request.onsuccess = () => r(request.result);
    });
    return saved.assessments[0].photo.uri;
  });
  expect(photo).toMatch(/^data:image\//);
  await page
    .getByRole("button", { name: "Delete assessment", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Delete assessment and photos" })
    .click();
  await expect(
    page.getByRole("button", { name: "Assess a room" }),
  ).toBeVisible();
});

test("no-hazards sample has qualified copy and no phantom checklist items", async ({
  page,
}) => {
  await sampleAssessment(page, "No obvious hazards");
  await expect(
    page.getByText(/not a declaration that the room is safe/),
  ).toBeVisible();
  await expect(page.getByRole("checkbox")).toHaveCount(0);
});

test("camera denial offers alternate input and a usable next step", async ({
  page,
}) => {
  await start(page, "Camera permission denied");
  await page.getByRole("button", { name: "Take photo", exact: true }).click();
  await expect(
    page.getByText("Camera access is off", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Use living room sample" }).click();
  await submitRoom(page);
  await expect(page.getByText("0 of 3 handled", { exact: true })).toBeVisible();
});

test("storage write failure never shows a status as saved", async ({
  page,
}) => {
  await sampleAssessment(page);
  await page.evaluate(() => {
    const original = IDBObjectStore.prototype.put;
    IDBObjectStore.prototype.put = function (
      ...args: Parameters<typeof original>
    ) {
      if ((window as any).failWrites)
        throw new DOMException("Preview storage is full", "QuotaExceededError");
      return original.apply(this, args);
    };
    (window as any).failWrites = true;
  });
  await page
    .getByRole("checkbox", {
      name: "Mark resolved: Check the tall cabinet",
      exact: true,
    })
    .click();
  await expect(
    page
      .getByText("Preview storage is full", { exact: true })
      .filter({ visible: true }),
  ).toBeVisible();
  await expect(page.getByText("0 of 3 handled", { exact: true })).toBeVisible();
  await page.evaluate(() => {
    (window as any).failWrites = false;
  });
  await page
    .getByRole("checkbox", {
      name: "Mark resolved: Check the tall cabinet",
      exact: true,
    })
    .click();
  await expect(page.getByText("1 of 3 handled", { exact: true })).toBeVisible();
});

test("interrupted analysis resumes with manual retry rather than claiming success", async ({
  page,
}) => {
  await start(page);
  await page.getByRole("button", { name: "Use living room sample" }).click();
  await submitRoom(page);
  await expect(
    page.getByText(
      "Loading a predefined example. Your photo is not sent anywhere.",
      { exact: true },
    ),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByText(/The preview was interrupted/)).toBeVisible();
  await page.getByRole("button", { name: "Retry analysis" }).click();
  await expect(page.getByText("0 of 3 handled", { exact: true })).toBeVisible();
});

test("handling every item remains qualified and reopening restores an open item", async ({
  page,
}) => {
  await sampleAssessment(page);
  for (const title of [
    "Check the tall cabinet",
    "Give the walkway more room",
    "Put small items out of reach",
  ]) {
    await page
      .getByRole("checkbox", { name: `Mark resolved: ${title}`, exact: true })
      .click();
  }
  await expect(
    page.getByText("You’ve reviewed every finding", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(/does not certify the room’s safety/),
  ).toBeVisible();
  await page
    .getByRole("checkbox", {
      name: "Reopen: Check the tall cabinet",
      exact: true,
    })
    .click();
  await expect(
    page.getByText("1 open · 2 resolved · 0 dismissed", { exact: true }),
  ).toBeVisible();
});

test("preview reset removes assessments and the unfinished draft only after confirmation", async ({
  page,
}) => {
  await sampleAssessment(page);
  await page
    .getByRole("button", { name: "New assessment", exact: true })
    .click();
  await page.getByRole("button", { name: "Use quiet room sample" }).click();
  await page
    .getByRole("button", { name: "Preview tools", exact: true })
    .click();
  await page.getByRole("button", { name: "Reset all preview data" }).click();
  await page.getByRole("button", { name: "Keep it", exact: true }).click();
  await page.getByRole("button", { name: "Reset all preview data" }).click();
  await page
    .getByRole("button", { name: "Reset all data", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Assess a room" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Assess a room" }),
  ).toBeVisible();
});

test("phone and desktop layouts have no horizontal overflow and produce review screenshots", async ({
  page,
}) => {
  await page.goto("/");
  await page.screenshot({
    path: "../.tools/screenshots/start-phone.png",
    fullPage: true,
  });
  await sampleAssessment(page);
  for (const width of [320, 430, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(
      page.getByRole("button", { name: "New assessment", exact: true }),
    ).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    );
    expect(overflow).toBe(false);
    await page.screenshot({
      path: `../.tools/screenshots/checklist-${width}.png`,
      fullPage: true,
    });
  }
});
