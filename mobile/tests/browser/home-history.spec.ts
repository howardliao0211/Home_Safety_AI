import { expect, test } from "@playwright/test";

test("Home retains a draft and reopens previous assessments after restart", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByText("Previous assessments", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Assess a room", exact: true })
    .click();
  await page.getByRole("button", { name: "Use living room sample" }).click();
  await page.getByRole("button", { name: "Review photo", exact: true }).click();
  await page.getByRole("button", { name: "Create sample assessment" }).click();
  await expect(page.getByText("0 of 3 handled", { exact: true })).toBeVisible();
  const first = page.url();
  await page.getByRole("button", { name: "Back to Home", exact: true }).click();
  await page.getByRole("button", { name: /^Open Living Room Review/ }).click();
  await expect(page).toHaveURL(first);
  await page
    .getByRole("checkbox", {
      name: "Mark resolved: Check the tall cabinet",
      exact: true,
    })
    .click();
  await page.getByRole("button", { name: "Back to Home", exact: true }).click();
  await expect(
    page.getByText("2 open findings", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Assess a room", exact: true })
    .click();
  await page.getByRole("button", { name: "Use quiet room sample" }).click();
  await page.goto("/");
  await page
    .getByRole("button", { name: "Assess a room", exact: true })
    .click();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Resume assessment", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Assess a room", exact: true })
    .click();
  await page.getByRole("button", { name: "Resume draft", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Use quiet room sample" }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.goto("/");
  await page
    .getByRole("button", { name: "Assess a room", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Discard draft and start new", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Review photo", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Use quiet room sample" }).click();
  await page.getByRole("button", { name: "Review photo", exact: true }).click();
  await page.getByRole("button", { name: "Create sample assessment" }).click();
  await expect(page.getByText("0 of 3 handled", { exact: true })).toBeVisible();
  await page.goto("/");
  await page.reload();
  await expect(page.getByRole("button", { name: /^Open / })).toHaveCount(2);
  for (const width of [320, 430, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth,
      ),
    ).toBe(false);
    await page.screenshot({
      path: `../.tools/screenshots/home-history-${width}.png`,
      fullPage: true,
    });
  }
  await page.getByRole("button", { name: /^Open Living Room Review/ }).click();
  await expect(page).toHaveURL(first);
  await expect(page.getByText("1 of 3 handled", { exact: true })).toBeVisible();
});

test("history displays long and missing titles with their date", async ({
  page,
}) => {
  await page.goto("/");
  for (const scenario of ["A closer look", "No obvious hazards"]) {
    await page
      .getByRole("button", { name: "Preview tools", exact: true })
      .click();
    await page.getByRole("radio", { name: scenario, exact: true }).click();
    await page.getByRole("button", { name: "Start fresh demo" }).click();
    await page.getByRole("button", { name: "Use living room sample" }).click();
    await page
      .getByRole("button", { name: "Review photo", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Create sample assessment" })
      .click();
    await expect(
      page.getByRole("button", { name: "New assessment", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Back to Home", exact: true })
      .click();
  }
  const long = page.getByRole("button", {
    name: /^Open Living room with a tall cabinet beside the sitting area,/,
  });
  await expect(
    long.getByText("Living room with a tall cabinet beside the…", {
      exact: true,
    }),
  ).toBeVisible();
  const fallback = page.getByRole("button", { name: /^Open Room assessment,/ });
  await expect(
    fallback.getByText("Room assessment", { exact: true }),
  ).toBeVisible();
  await expect(
    fallback.getByText(new Date().getFullYear().toString(), { exact: false }),
  ).toBeVisible();
});
