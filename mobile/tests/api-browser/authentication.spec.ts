import { expect, test } from "@playwright/test";

test("unverified account deletion stays pending until server cleanup is confirmed", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Email", exact: true })
    .fill(`${crypto.randomUUID()}@example.test`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("Strong-password-123");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Verify your email" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Delete account", exact: true })
    .click();
  await page
    .getByLabel("Password", { exact: true })
    .fill("Strong-password-123");
  await page
    .getByRole("button", { name: "Permanently delete account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Deleting your account" }),
  ).toBeVisible();
  await expect(
    page.getByText("Your account and associated data have been deleted.", {
      exact: true,
    }),
  ).toHaveCount(0);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Deleting your account" }),
  ).toBeVisible();
  await request.post("http://127.0.0.1:8001/__test/control", {
    data: { finish_deletions: true },
  });
  await page
    .getByRole("button", { name: "Check deletion status", exact: true })
    .click();
  await expect(
    page.getByText("Your account and associated data have been deleted.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Sign in", exact: true }),
  ).toBeVisible();
});

test("account bootstrap storage failures offer a working retry", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const read = Storage.prototype.getItem;
    let fail = true;
    Storage.prototype.getItem = function (key: string) {
      if (fail && key.startsWith("deletion:")) {
        fail = false;
        throw new Error("storage unavailable");
      }
      return read.call(this, key);
    };
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Retry opening account" }).click();
  await expect(
    page.getByRole("heading", { name: "Sign in", exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: "../.tools/auth-login.png", fullPage: true });
});

test("registration, verification refresh, sign-out isolation and password recovery", async ({
  page,
  request,
}) => {
  const email = `${crypto.randomUUID()}@example.test`;
  const endpoint =
    "http://127.0.0.1:9099/identitytoolkit.googleapis.com/v1/accounts:";
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(email);
  await page
    .getByLabel("Password", { exact: true })
    .fill("Strong-password-123");
  await page
    .getByRole("button", { name: "Show password", exact: true })
    .click();
  await expect(page.getByLabel("Password", { exact: true })).toHaveJSProperty(
    "type",
    "text",
  );
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Verify your email" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "I’ve verified my email" }).click();
  await expect(page.getByText(/Your email is not verified yet/)).toBeVisible();
  const codes = await (
    await request.get(
      "http://127.0.0.1:9099/emulator/v1/projects/home-safety-local/oobCodes",
    )
  ).json();
  const action = codes.oobCodes.find(
    (code: { email: string; requestType: string }) =>
      code.email === email && code.requestType === "VERIFY_EMAIL",
  );
  expect(action).toBeTruthy();
  expect(
    (
      await request.post(endpoint + "update?key=local", {
        data: { oobCode: action.oobCode },
      })
    ).ok(),
  ).toBeTruthy();
  await page.getByRole("button", { name: "I’ve verified my email" }).click();
  await expect(
    page.getByRole("button", { name: "Start with a room" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Start with a room" }).click();
  await page.getByRole("button", { name: "Use living room sample" }).click();
  await page.getByRole("button", { name: "Account", exact: true }).click();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Sign in", exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Sign in", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("img", { name: /room/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Forgot password?" }).click();
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(email);
  await page.getByRole("button", { name: "Send reset email" }).click();
  await expect(
    page.getByText(/If an account can receive a reset email/),
  ).toBeVisible();
  const resetCodes = await (
    await request.get(
      "http://127.0.0.1:9099/emulator/v1/projects/home-safety-local/oobCodes",
    )
  ).json();
  const reset = resetCodes.oobCodes.find(
    (code: { email: string; requestType: string }) =>
      code.email === email && code.requestType === "PASSWORD_RESET",
  );
  expect(reset).toBeTruthy();
  expect(
    (
      await request.post(endpoint + "resetPassword?key=local", {
        data: { oobCode: reset.oobCode, newPassword: "Changed-password-456" },
      })
    ).ok(),
  ).toBeTruthy();
  expect(
    (
      await request.post(endpoint + "signInWithPassword?key=local", {
        data: {
          email,
          password: "Strong-password-123",
          returnSecureToken: true,
        },
      })
    ).ok(),
  ).toBeFalsy();
  await page.getByRole("button", { name: "Back to sign in" }).click();
  await page
    .getByLabel("Password", { exact: true })
    .fill("Changed-password-456");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Start with a room" }),
  ).toBeVisible();
});
