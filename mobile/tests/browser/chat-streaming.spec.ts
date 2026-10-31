import { expect, test, type Page } from "@playwright/test";

async function openChat(page: Page, scenario: string) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Preview tools", exact: true })
    .click();
  await page.getByRole("radio", { name: scenario, exact: true }).click();
  await page.getByRole("button", { name: "Start fresh demo" }).click();
  await page.getByRole("button", { name: "Use living room sample" }).click();
  await page.getByRole("button", { name: "Review photo", exact: true }).click();
  await page.getByRole("button", { name: "Create sample assessment" }).click();
  await page
    .getByRole("button", { name: "View Check the tall cabinet", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Chat about it", exact: true })
    .click();
}
const question = (page: Page) =>
  page.getByRole("textbox", { name: "Your question", exact: true });

test("a reply grows in one message, keeps running away from the screen, and completes once", async ({
  page,
}) => {
  await openChat(page, "Everyday hazards");
  await question(page).fill("What should I do first?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByText("Waiting to start…")).toBeVisible();
  await expect(page.getByText("Writing…")).toBeVisible();
  const growing = page.getByText(/^Simulated guidance/);
  await expect(growing).toBeVisible();
  const early = (await growing.textContent())!.length;
  // Send stays disabled while the job runs; a separate draft stays editable.
  await expect(
    page.getByRole("button", { name: "Send", exact: true }),
  ).toBeDisabled();
  await question(page).fill("A separate draft");
  // Leave and return: the job continued without this screen.
  await page
    .getByRole("button", { name: "Back to finding", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Chat about it", exact: true })
    .click();
  await expect(page.getByText(/You decide whether to change/)).toBeVisible();
  expect(
    (await page.getByText(/^Simulated guidance/).textContent())!.length,
  ).toBeGreaterThan(early);
  await expect(page.getByText("Writing…")).toHaveCount(0);
  await expect(page.getByTestId("chat-user-message")).toHaveCount(1);
  await expect(question(page)).toHaveValue("A separate draft");
});

test("an interrupted reply is labelled incomplete and retry replaces it", async ({
  page,
}) => {
  await openChat(page, "Chat reply retry");
  await question(page).fill("How should I think about this?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(
    page.getByText("INCOMPLETE RESPONSE", { exact: true }),
  ).toBeVisible();
  const partial = await page.getByText(/^Simulated guidance/).textContent();
  expect(partial!.split(" ").length).toBeLessThan(10);
  await expect(
    page.getByText(/^The simulated reply was interrupted/),
  ).toBeVisible();
  await question(page).fill("My next question stays here.");
  await page.reload();
  await expect(
    page.getByText("INCOMPLETE RESPONSE", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Retry reply", exact: true }).click();
  await expect(
    page.getByText("INCOMPLETE RESPONSE", { exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText(/You decide whether to change/)).toBeVisible();
  await expect(page.getByText(/^Simulated guidance/)).toHaveCount(1);
  await expect(page.getByTestId("chat-user-message")).toHaveCount(1);
  await expect(question(page)).toHaveValue("My next question stays here.");
});
