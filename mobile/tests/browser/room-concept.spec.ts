import { expect, test, type Page } from "@playwright/test";

async function assess(page: Page, scenario: string, sample = "living room") {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Preview tools", exact: true })
    .click();
  await page.getByRole("radio", { name: scenario, exact: true }).click();
  await page.getByRole("button", { name: "Start fresh demo" }).click();
  await page.getByRole("button", { name: `Use ${sample} sample` }).click();
  await page.getByRole("button", { name: "Review photo", exact: true }).click();
  await page.getByRole("button", { name: "Create sample assessment" }).click();
}

test("concept compares the original and generated images without zoom controls", async ({
  page,
}, testInfo) => {
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
  await expect(page.getByRole("img")).toHaveCount(2, { timeout: 20000 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("room-concept-ready.png"),
    fullPage: true,
  });
  await expect(page.getByRole("button", { name: "Zoom in" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Fit image" })).toHaveCount(0);
  const original = page.getByRole("img", {
    name: "Living room sample",
    exact: true,
  });
  const generated = page.getByRole("img", {
    name: /AI-generated room concept/,
  });
  const originalBox = (await original.boundingBox())!;
  const generatedBox = (await generated.boundingBox())!;
  expect(generatedBox.y).toBeGreaterThanOrEqual(
    originalBox.y + originalBox.height,
  );
  for (const width of [320, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    await expect
      .poll(async () => {
        const a = (await original.boundingBox())!;
        const b = (await generated.boundingBox())!;
        return width < 600 ? b.y >= a.y + a.height : b.x >= a.x + a.width;
      })
      .toBe(true);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  }
  await page.screenshot({
    path: testInfo.outputPath("room-concept-wide.png"),
    fullPage: true,
  });
  await page.reload();
  await expect(page.getByRole("img")).toHaveCount(2);
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
  await expect(
    page.getByRole("img", { name: "Living room sample", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: /AI-generated room concept/ }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Retry room concept" }).click();
  await expect(
    page.getByText("Generating room concept…", { exact: true }).last(),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "Living room sample", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("img")).toHaveCount(2, { timeout: 20000 });
  await assess(page, "No obvious hazards");
  await expect(page.getByText(/Nothing obvious/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "View room concept" }),
  ).toHaveCount(0);
});

test("unavailable concept keeps the whole original portrait photo visible", async ({
  page,
}) => {
  await assess(page, "Everyday hazards", "portrait room");
  await page.getByRole("button", { name: "View room concept" }).click();
  await expect(
    page
      .getByText("Room concepts are currently unavailable.", { exact: true })
      .last(),
  ).toBeVisible();
  const original = page.getByRole("img", {
    name: "Portrait room sample",
    exact: true,
  });
  await expect(original).toBeVisible();
  await expect
    .poll(async () => {
      const box = (await original.boundingBox())!;
      return box.height / box.width;
    })
    .toBeCloseTo(1.5, 1);
  await expect(page.getByRole("img")).toHaveCount(1);
  await expect(
    page.getByRole("button", { name: "Retry room concept" }),
  ).toHaveCount(0);
});
