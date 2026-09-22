import { test, expect } from "@playwright/test";

test.describe("Shared Page", () => {
  test("shows Shared heading or redirects to login", async ({ page }) => {
    await page.goto("/shared");
    const heading = page.getByRole("heading", { name: /Shared/i });
    const loginHeading = page.getByText("Sign in to your account");
    await expect(heading.or(loginHeading)).toBeVisible({ timeout: 10_000 });
  });

  test("shows empty state or shared items", async ({ page }) => {
    await page.goto("/shared");
    const heading = page.getByRole("heading", { name: /Shared/i });
    const loginHeading = page.getByText("Sign in to your account");
    await expect(heading.or(loginHeading)).toBeVisible({ timeout: 10_000 });

    if (await heading.isVisible().catch(() => false)) {
      const emptyState = page.getByText(/No shared|Nothing shared/i);
      const items = page.locator("[class*='grid'] > *, [class*='divide'] > *").first();
      await expect(emptyState.or(items)).toBeVisible({ timeout: 10_000 });
    }
  });
});

test.describe("Recently Deleted Page", () => {
  test("shows Recently deleted heading or redirects to login", async ({ page }) => {
    await page.goto("/recently-deleted");
    const heading = page.getByRole("heading", { name: /Recently deleted/i });
    const loginHeading = page.getByText("Sign in to your account");
    await expect(heading.or(loginHeading)).toBeVisible({ timeout: 10_000 });
  });

  test("shows empty state or deleted items", async ({ page }) => {
    await page.goto("/recently-deleted");
    const heading = page.getByRole("heading", { name: /Recently deleted/i });
    const loginHeading = page.getByText("Sign in to your account");
    await expect(heading.or(loginHeading)).toBeVisible({ timeout: 10_000 });

    if (await heading.isVisible().catch(() => false)) {
      const emptyState = page.getByText(/Nothing recently deleted|No deleted|No items/i);
      const items = page.locator("[class*='grid'] > *, [class*='divide'] > *").first();
      await expect(emptyState.or(items)).toBeVisible({ timeout: 10_000 });
    }
  });

  test("legacy /trash redirects to /recently-deleted", async ({ page }) => {
    await page.goto("/trash");
    const heading = page.getByRole("heading", { name: /Recently deleted/i });
    const loginHeading = page.getByText("Sign in to your account");
    await expect(heading.or(loginHeading)).toBeVisible({ timeout: 10_000 });
  });
});
