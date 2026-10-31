import { expect, test, type Page } from "@playwright/test";

async function assess(page: Page, scenario: string, details = "") {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Preview tools", exact: true })
    .click();
  await page.getByRole("radio", { name: scenario, exact: true }).click();
  await page.getByRole("button", { name: "Start fresh demo" }).click();
  await page.getByRole("button", { name: "Use living room sample" }).click();
  if (details)
    await page
      .getByRole("textbox", { name: "Household details (optional)" })
      .fill(details);
  await page.getByRole("button", { name: "Review photo", exact: true }).click();
  await page.getByRole("button", { name: "Create sample assessment" }).click();
}

test("new results show three saved suggestions after the photo; zero findings and legacy records do not", async ({
  page,
}) => {
  await assess(page, "Everyday hazards", "Grandpa uses a walker");
  const heading = page.getByRole("heading", { name: "Where to start" });
  await expect(heading).toBeVisible();
  const items = page.getByRole("listitem");
  await expect(items).toHaveCount(3);
  await expect(items.nth(1)).toContainText("Grandpa uses a walker");
  const photo = await page.getByRole("img").first().boundingBox();
  const summary = await heading.boundingBox();
  expect(photo!.y).toBeLessThan(summary!.y);
  // Status changes and restart keep the same saved items.
  const before = await items.allTextContents();
  await page
    .getByRole("checkbox", { name: "Mark resolved: Check the tall cabinet" })
    .click();
  await page.reload();
  await expect(page.getByRole("listitem")).toHaveText(before);

  await assess(page, "No obvious hazards");
  await expect(page.getByText("Nothing obvious")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Where to start" }),
  ).toHaveCount(0);

  await assess(page, "Saved before suggestions");
  await expect(page.getByText(/saved before suggestions/)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Where to start" }),
  ).toHaveCount(0);
});
