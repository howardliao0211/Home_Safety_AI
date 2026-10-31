import { expect, test, type Page } from "@playwright/test";

async function assessment(page: Page, retry = false) {
  await page.goto("/");
  if (retry) {
    await page
      .getByRole("button", { name: "Preview tools", exact: true })
      .click();
    await page
      .getByRole("radio", { name: "Chat reply retry", exact: true })
      .click();
    await page.getByRole("button", { name: "Start fresh demo" }).click();
  } else
    await page
      .getByRole("button", { name: "Assess a room", exact: true })
      .click();
  await page.getByRole("button", { name: "Use living room sample" }).click();
  await page.getByRole("button", { name: "Review photo", exact: true }).click();
  await page.getByRole("button", { name: "Create sample assessment" }).click();
  await page
    .getByRole("button", { name: "View Check the tall cabinet", exact: true })
    .click();
}

test("chat replaces evidence controls, retains drafts, replies and checklist status", async ({
  page,
}) => {
  await assessment(page);
  await expect(page).toHaveURL(/\/finding\//);
  const finding = page.url();
  await expect(
    page.getByRole("button", { name: "Ask AI to check" }),
  ).toHaveCount(0);
  await expect(page.getByText("A CLOSER LOOK", { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Add a close-up photo" }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Chat about it", exact: true })
    .click();
  await expect(
    page.getByText(/Ask questions about this finding/),
  ).toBeVisible();
  const question = page.getByRole("textbox", {
    name: "Your question",
    exact: true,
  });
  await question.fill("What could I do first?");
  await page
    .getByRole("button", { name: "Back to finding", exact: true })
    .click();
  await expect(page).toHaveURL(finding);
  await page
    .getByRole("button", { name: "Chat about it", exact: true })
    .click();
  await expect(question).toHaveValue("What could I do first?");
  await page.reload();
  await expect(question).toHaveValue("What could I do first?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(
    page
      .getByTestId("chat-user-message")
      .filter({ hasText: "What could I do first?" }),
  ).toBeVisible();
  await expect(page.getByText(/Simulated guidance about/)).toBeVisible();
  await expect(question).toHaveValue("");
  await question.fill("Does that help children too?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByText(/As in our earlier discussion/)).toBeVisible();
  await page
    .getByRole("button", { name: "Back to finding", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Mark resolved", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Mark resolved", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Chat about it", exact: true })
    .click();
  await expect(
    page
      .getByTestId("chat-user-message")
      .filter({ hasText: "What could I do first?" }),
  ).toBeVisible();
  for (const width of [320, 430, 1280]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
    ).toBe(false);
  }
  await page
    .getByRole("button", { name: "Back to finding", exact: true })
    .click();
  await page.goto(finding.replace("/finding/", "/evidence/") + "?kind=review");
  await expect(page).toHaveURL(finding);
  await expect(
    page.getByRole("button", { name: "Chat about it", exact: true }),
  ).toBeVisible();
});

test("failed chat is saved across restart and retry preserves a new draft", async ({
  page,
}) => {
  await assessment(page, true);
  await page
    .getByRole("button", { name: "Chat about it", exact: true })
    .click();
  const question = page.getByRole("textbox", {
    name: "Your question",
    exact: true,
  });
  await question.fill("How should I think about this?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Retry reply", exact: true }),
  ).toBeVisible();
  await question.fill("My next question stays here.");
  await page.reload();
  await expect(question).toHaveValue("My next question stays here.");
  await expect(
    page.getByRole("button", { name: "Send", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Retry reply", exact: true }).click();
  await expect(page.getByText(/Simulated guidance about/)).toBeVisible();
  await expect(
    page.getByText("How should I think about this?", { exact: true }),
  ).toHaveCount(1);
  await expect(question).toHaveValue("My next question stays here.");
});

test("draft storage failure recovers without masking later reply announcements", async ({
  page,
}) => {
  await assessment(page);
  await page
    .getByRole("button", { name: "Chat about it", exact: true })
    .click();
  await page.evaluate(() => {
    const original = IDBObjectStore.prototype.put;
    IDBObjectStore.prototype.put = function (
      ...args: Parameters<typeof original>
    ) {
      if ((window as any).failChatDraft)
        throw new DOMException(
          "Draft storage unavailable",
          "QuotaExceededError",
        );
      return original.apply(this, args);
    };
    (window as any).failChatDraft = true;
  });
  const question = page.getByRole("textbox", {
    name: "Your question",
    exact: true,
  });
  await question.fill("A question while storage fails");
  await expect(
    page.getByText("Draft storage unavailable", { exact: true }),
  ).toBeVisible();
  await page.evaluate(() => {
    (window as any).failChatDraft = false;
  });
  await question.fill("My recovered question");
  await expect(
    page.getByText("Draft storage unavailable", { exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText(/Draft could not save|Saving draft/)).toHaveCount(
    0,
  );
  await expect(page.getByText(/Draft saved on this device/)).toHaveCount(0);
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(
    page.getByText("Reply available.", { exact: true }),
  ).toBeVisible();
});
