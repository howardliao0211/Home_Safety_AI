import { expect, test, type Page } from "@playwright/test";
import { restorePortraitDraft } from "./helpers/portrait-photo";

async function assess(page: Page, scenario: string, sample: string) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Preview tools", exact: true })
    .click();
  await page.getByRole("radio", { name: scenario, exact: true }).click();
  await page.getByRole("button", { name: "Start fresh demo" }).click();
  if (sample === "portrait room") await restorePortraitDraft(page);
  else await page.getByRole("button", { name: `Use ${sample} sample` }).click();
  await page.getByRole("button", { name: "Review photo", exact: true }).click();
  await page.getByRole("button", { name: "Create sample assessment" }).click();
}
const masks = (page: Page) =>
  page.locator('img[src^="data:image/svg+xml"]').locator("visible=true");

test("portrait photo is shown whole with progressive severity highlights for open findings only", async ({
  page,
}) => {
  await assess(page, "Everyday hazards", "portrait room");
  const photo = page.getByRole("img", { name: "Portrait room sample" });
  await expect(photo).toBeVisible();
  // Two of three appear first; the staged third arrives without visiting details.
  await expect(
    page.getByText(/Highlights available for 2 of 3 open findings/),
  ).toBeVisible();
  await expect(
    page.getByText(/Highlights available for 3 of 3 open findings/),
  ).toBeVisible({ timeout: 10_000 });
  await expect(masks(page)).toHaveCount(3);
  for (const label of ["High priority", "Medium priority", "Low priority"])
    await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
  // Whole portrait photo: the canvas keeps the 2:3 source aspect, uncropped.
  const box = (await photo.boundingBox())!;
  expect(box.height / box.width).toBeCloseTo(1.5, 1);
  const first = (await masks(page).first().boundingBox())!;
  expect(first).toEqual(box);
  // Photo comes before the suggestions.
  const heading = (await page
    .getByRole("heading", { name: "Where to start" })
    .boundingBox())!;
  expect(box.y + box.height).toBeLessThanOrEqual(heading.y);

  await page
    .getByRole("checkbox", { name: "Mark resolved: Check the tall cabinet" })
    .click();
  await expect(masks(page)).toHaveCount(2);
  await expect(
    page.getByText(/Highlights available for 2 of 2 open findings/),
  ).toBeVisible();
  await page
    .getByRole("checkbox", { name: "Reopen: Check the tall cabinet" })
    .click();
  await expect(masks(page)).toHaveCount(3);

  await page
    .getByRole("button", { name: "Hide highlights", exact: true })
    .click();
  await expect(masks(page)).toHaveCount(0);
  await expect(photo).toBeVisible();
  await expect(page.getByText(/Highlights hidden/)).toBeVisible();
  await expect(
    page.getByRole("checkbox", {
      name: "Mark resolved: Check the tall cabinet",
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Show highlights", exact: true })
    .click();
  await expect(masks(page)).toHaveCount(3);
  await page
    .getByRole("button", { name: "Hide highlights", exact: true })
    .click();
  await page
    .getByRole("button", { name: "View room concept", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Back to checklist", exact: true })
    .click();
  await expect(masks(page)).toHaveCount(3);
  await expect(
    page.getByRole("button", { name: "Hide highlights", exact: true }),
  ).toBeVisible();

  // Alignment survives a resize.
  await page.setViewportSize({ width: 320, height: 800 });
  const narrow = (await photo.boundingBox())!;
  expect(await masks(page).first().boundingBox()).toEqual(narrow);
  expect(narrow.height / narrow.width).toBeCloseTo(1.5, 1);
});

test("finding details show the finding's severity colour; unsupported findings are explicit", async ({
  page,
}) => {
  await assess(page, "Everyday hazards", "living room");
  await page
    .getByRole("button", { name: "View Check the tall cabinet", exact: true })
    .click();
  await expect(masks(page)).toHaveCount(1);
  const src = await masks(page).first().getAttribute("src");
  expect(decodeURIComponent(src!)).toContain("#dc2626");
  await expect(
    page
      .getByLabel("Highlight colours: Red for High priority.", { exact: true })
      .locator("visible=true"),
  ).toHaveCount(1);

  await assess(page, "A closer look", "living room");
  await expect(
    page.getByText(/Highlights available for 0 of 1 open finding/),
  ).toBeVisible();
  await expect(masks(page)).toHaveCount(0);
});
