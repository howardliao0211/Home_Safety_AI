import { expect, test, type Page } from "@playwright/test";

const details = (page: Page) =>
  page.getByRole("textbox", {
    name: "Household details (optional)",
    exact: true,
  });
// Displayed text, excluding the retained capture textbox, with exact line breaks.
async function expectSaved(page: Page, text: string) {
  const shown = page.getByText(text, { exact: true }).and(page.locator("div"));
  await expect(shown).toBeVisible();
  expect(await shown.textContent()).toBe(text);
}
async function begin(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Assess a room", exact: true })
    .click();
  await expect(details(page)).toBeVisible();
}

test("household details persist through a text-only draft, confirmation edits and the saved assessment", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await begin(page);
  await expect(
    page.getByText(
      "Choose any groups that apply, and add details below if you’d like. Both are optional.",
    ),
  ).toBeVisible();
  await expect(details(page)).toHaveAttribute(
    "placeholder",
    "For example, a 2-year-old, an adult who uses a walker, or two indoor cats.",
  );
  await expect(details(page)).toHaveValue("");
  await details(page).fill("  A 2-year-old\n\n  and two  cats  ");
  await expect(page.getByText("29 / 3,000 characters")).toBeVisible();
  // Text alone does not bypass the photo requirement.
  await expect(
    page.getByRole("button", { name: "Review photo", exact: true }),
  ).toBeDisabled();
  await page.goto("/");
  await page.reload();
  await page.getByRole("button", { name: "Resume assessment" }).click();
  await expect(details(page)).toHaveValue(
    "  A 2-year-old\n\n  and two  cats  ",
  );
  // A text-only draft gets discard protection; keeping it retains the text.
  await page.getByRole("button", { name: "Cancel new assessment" }).click();
  await expect(page.getByText("Discard this submission?")).toBeVisible();
  await page.getByRole("button", { name: "Keep it", exact: true }).click();
  await expect(details(page)).toHaveValue(
    "  A 2-year-old\n\n  and two  cats  ",
  );

  // Overlong pasted text is kept, explained, and blocks review.
  await page.getByRole("button", { name: "Use living room sample" }).click();
  const overlong = "🐈".repeat(3001);
  await details(page).fill(overlong);
  await expect(
    page.getByText("Keep household details to 3,000 characters or fewer."),
  ).toBeVisible();
  await expect(page.getByText("3,001 / 3,000 characters")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Review photo", exact: true }),
  ).toBeDisabled();
  await expect(details(page)).toHaveValue(overlong);
  await details(page).fill("🐈".repeat(3000));
  await expect(
    page.getByText("Keep household details to 3,000 characters or fewer."),
  ).toHaveCount(0);

  await details(page).fill("  A 2-year-old\n  and two cats\n");
  await page.getByRole("button", { name: "Review photo", exact: true }).click();
  await expect(
    page.getByText("No groups selected", { exact: true }),
  ).toBeVisible();
  await expectSaved(page, "A 2-year-old\n  and two cats");
  await page
    .getByRole("button", { name: "Edit photo or household details" })
    .click();
  await expect(details(page)).toHaveValue("  A 2-year-old\n  and two cats\n");
  await page.getByRole("checkbox", { name: "Pet", exact: true }).click();
  await expect(details(page)).toHaveValue("  A 2-year-old\n  and two cats\n");
  await page.getByRole("button", { name: "Review photo", exact: true }).click();
  await expect(page.getByText("Pet", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Create sample assessment" }).click();
  await expect(page.getByText("0 of 3 handled", { exact: true })).toBeVisible();
  await expectSaved(page, "A 2-year-old\n  and two cats");
  await page.reload();
  await expectSaved(page, "A 2-year-old\n  and two cats");
  await expect(
    page.getByText(/Simulated|sample|preview/i).first(),
  ).toBeVisible();

  // A fresh draft starts blank.
  await begin(page);
  await expect(details(page)).toHaveValue("");
  await page.getByRole("button", { name: "Use living room sample" }).click();
  await page.getByRole("button", { name: "Review photo", exact: true }).click();
  await expect(
    page.getByText("No additional details", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Your household · General assessment", { exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("a failed household-details save is reported and the typed text is kept", async ({
  page,
}) => {
  await begin(page);
  await page.evaluate(() => {
    const original = IDBObjectStore.prototype.put;
    IDBObjectStore.prototype.put = function (
      ...args: Parameters<typeof original>
    ) {
      if ((window as any).failSave)
        throw new DOMException("Storage unavailable", "QuotaExceededError");
      return original.apply(this, args);
    };
    (window as any).failSave = true;
  });
  await details(page).fill("Two indoor cats");
  await expect(
    page.getByText(/Household details could not be saved/),
  ).toBeVisible();
  await expect(details(page)).toHaveValue("Two indoor cats");
  await page.evaluate(() => ((window as any).failSave = false));
  await details(page).fill("Two indoor cats and a dog");
  await expect(
    page.getByText(/Household details could not be saved/),
  ).toHaveCount(0);
  await page.goto("/");
  await page.reload();
  await page.getByRole("button", { name: "Resume assessment" }).click();
  await expect(details(page)).toHaveValue("Two indoor cats and a dog");
});
