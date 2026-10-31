import { expect, test, type Page } from "@playwright/test";

async function assess(page: Page, scenario: string) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Preview tools", exact: true })
    .click();
  await page.getByRole("radio", { name: scenario, exact: true }).click();
  await page.getByRole("button", { name: "Start fresh demo" }).click();
  await page.getByRole("button", { name: "Use living room sample" }).click();
  await page.getByRole("button", { name: "Review photo", exact: true }).click();
  await page.getByRole("button", { name: "Create sample assessment" }).click();
}

test("concept stays hidden until opened, persists and shows only one image", async ({
  page,
}) => {
  await assess(page, "Everyday hazards");
  await expect(
    page.getByRole("button", { name: "View room concept" }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: /AI-generated room concept/ }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "View room concept" }).click();
  await expect(
    page.getByRole("heading", { name: "AI-generated room concept" }),
  ).toBeVisible();
  await expect(
    page.getByText(/It does not mean your room is safe/),
  ).toBeVisible();
  await expect(page.getByRole("img")).toHaveCount(1, { timeout: 20000 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../.tools/room-concept-ready.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Zoom in" }).click();
  await expect(page.getByRole("button", { name: "Fit image" })).toBeEnabled();
  await page.reload();
  await expect(page.getByRole("img")).toHaveCount(1);
  await expect(
    page.getByRole("button", { name: "Retry room concept" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Back to checklist" }).click();
  await expect(page.getByText("0 of 3 handled", { exact: true })).toBeVisible();
});

test("failed concept retries explicitly and no-findings skips the feature", async ({
  page,
}) => {
  await assess(page, "A closer look");
  await page.getByRole("button", { name: "View room concept" }).click();
  await page.getByRole("button", { name: "Retry room concept" }).click();
  await expect(
    page.getByText("Generating room concept…", { exact: true }).last(),
  ).toBeVisible();
  await expect(page.getByRole("img")).toHaveCount(1, { timeout: 20000 });
  await assess(page, "No obvious hazards");
  await expect(page.getByText(/Nothing obvious/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "View room concept" }),
  ).toHaveCount(0);
});
