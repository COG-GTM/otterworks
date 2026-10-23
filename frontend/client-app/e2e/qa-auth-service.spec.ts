import { test, expect, type Page } from "@playwright/test";
import {
  uniqueEmail,
  registerUser,
  loginUser,
  expectDashboard,
} from "./fixtures/test-helpers";

// QA audit of auth-service user flows; findings referenced as QA-AUTH-NN are
// documented in docs/qa/auth-service.md.

const PASSWORD = "QaAuthPass123!";

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });
  await expect(page.getByText("Sign in to your account")).toBeVisible();
}

function toggleFor(page: Page, label: string) {
  return page
    .locator("div.flex.items-center.justify-between", { hasText: label })
    .getByRole("button");
}

test.describe("QA auth-service: account lifecycle", () => {
  test("register, sign out, sign back in", async ({ page }) => {
    const email = uniqueEmail();
    await registerUser(page, { name: "QA Lifecycle", email, password: PASSWORD });
    await expectDashboard(page);

    await signOut(page);
    const tokens = await page.evaluate(() => [
      localStorage.getItem("otter_access_token"),
      localStorage.getItem("otter_refresh_token"),
    ]);
    expect(tokens).toEqual([null, null]);

    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });

    await loginUser(page, email, PASSWORD);
    await expectDashboard(page);
  });

  test("wrong password shows an error and stays on login", async ({ page }) => {
    const email = uniqueEmail();
    await registerUser(page, { name: "QA BadPw", email, password: PASSWORD });
    await expectDashboard(page);
    await signOut(page);

    await loginUser(page, email, "DefinitelyWrong999!");
    await expect(
      page.getByText("Invalid email or password. Please try again.")
    ).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
    expect(
      await page.evaluate(() => localStorage.getItem("otter_access_token"))
    ).toBeNull();
  });

  test("duplicate email registration shows an error", async ({ page }) => {
    const email = uniqueEmail();
    await registerUser(page, { name: "QA Dup", email, password: PASSWORD });
    await expectDashboard(page);
    await signOut(page);

    await registerUser(page, { name: "QA Dup Two", email, password: PASSWORD });
    await expect(
      page.getByText("Registration failed. This email may already be in use.")
    ).toBeVisible();
    await expect(page).toHaveURL(/\/register/);
  });
});

test.describe("QA auth-service: settings persistence", () => {
  test.beforeEach(async ({ page }) => {
    await registerUser(page, { name: "QA Settings", password: PASSWORD });
    await expectDashboard(page);
    await page.goto("/settings");
    await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  });

  test("notification toggle persists after reload", async ({ page }) => {
    const desktop = toggleFor(page, "Desktop notifications");
    await expect(desktop).toHaveClass(/bg-gray-300/);

    const saved = page.waitForResponse(
      (r) => r.url().includes("/api/v1/settings") && r.request().method() === "PATCH"
    );
    await desktop.click();
    expect((await saved).status()).toBe(200);
    await expect(desktop).toHaveClass(/bg-otter-600/);

    await page.reload();
    await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
    await expect(toggleFor(page, "Desktop notifications")).toHaveClass(/bg-otter-600/);
    await expect(toggleFor(page, "Email notifications")).toHaveClass(/bg-otter-600/);
  });

  test("profile display name edit persists after reload", async ({ page }) => {
    test.fail(
      true,
      "QA-AUTH-01: Settings 'Save changes' sends PATCH /api/v1/auth/profile, which auth-service does not map (500)"
    );
    await page.getByLabel("Full name").fill("QA Renamed User");
    await page.getByRole("button", { name: /Save changes/i }).click();
    await expect(page.getByText("Profile updated successfully.")).toBeVisible({
      timeout: 5_000,
    });

    await page.reload();
    await expect(page.getByLabel("Full name")).toHaveValue("QA Renamed User", {
      timeout: 5_000,
    });
  });
});
