import { test, expect, type Page } from "@playwright/test";

// QA admin-audit e2e: drives the Angular admin-dashboard (not the client-app),
// so every URL is absolute against ADMIN_DASHBOARD_URL. Requires the dashboard,
// admin-service and seeded admin_users (scripts/seed.py). Findings QA-AA-N are
// documented in docs/qa/admin-audit.md.
const ADMIN_URL = process.env.ADMIN_DASHBOARD_URL || "http://localhost:4200";
const LOGIN_EMAIL = "qa-e2e-admin@otterworks.io";

async function login(page: Page) {
  await page.goto(`${ADMIN_URL}/login`);
  await page.getByLabel("Email").fill(LOGIN_EMAIL);
  await page.getByLabel("Password").fill("qa-e2e-password");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 });
}

async function openFirstActiveUser(page: Page): Promise<string> {
  await page.goto(`${ADMIN_URL}/users`);
  const rows = page.locator("tr.table-row");
  await expect(rows.first()).toBeVisible();
  const active = rows.filter({ hasText: /active/i }).filter({ hasNotText: /admin/i }).first();
  const name = (await active.locator("td").first().innerText()).split("\n")[0].trim();
  await page.getByPlaceholder("Search by name or email").fill(name);
  await expect(rows.first()).toContainText(name);
  await rows.first().click();
  await expect(page).toHaveURL(/\/users\/[0-9a-f-]{36}/);
  return page.url().split("/users/")[1];
}

test.describe("QA admin-audit dashboard", () => {
  test.describe.configure({ mode: "serial" });

  test("unauthenticated visitors are redirected to login", async ({ page }) => {
    await page.goto(`${ADMIN_URL}/users`);
    await expect(page).toHaveURL(/\/login/);
  });

  test("suspend + restore a user and see both actions in the audit log", async ({ page }) => {
    await login(page);
    const userId = await openFirstActiveUser(page);
    const started = Date.now();

    await page.getByRole("button", { name: /suspend user/i }).click();
    await page.getByRole("dialog").getByRole("button", { name: /^suspend$/i }).click();
    await expect(page.getByRole("button", { name: /restore user/i })).toBeVisible();
    await page.getByRole("button", { name: /restore user/i }).click();
    await expect(page.getByRole("button", { name: /suspend user/i })).toBeVisible();

    await page.goto(`${ADMIN_URL}/audit`);
    await page.getByPlaceholder("Search by user, action, or resource").fill(userId);
    const rows = page.locator("tr[mat-row]");
    await expect(rows.filter({ hasText: /suspend/i }).first()).toBeVisible();
    await expect(rows.filter({ hasText: /restore/i }).first()).toBeVisible();

    const res = await page.request.get(`${ADMIN_URL}/api/v1/admin/audit-logs`, {
      headers: { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem("ow_admin_token"))}` },
      params: { resource_id: userId, resource_type: "AdminUser" },
    });
    const logs = (await res.json()).audit_logs as Array<{ action: string; created_at: string }>;
    const recent = logs.filter((l) => Date.parse(l.created_at) >= started - 5_000);
    expect(recent.map((l) => l.action)).toEqual(expect.arrayContaining(["user.suspended", "user.activated"]));
  });

  test("audit entries are attributed to the signed-in admin (QA-AA-1)", async ({ page }) => {
    test.fail(true, "QA-AA-1: dashboard login is mocked; every session uses a hard-coded admin@otterworks.dev JWT");
    await login(page);
    const userId = await openFirstActiveUser(page);
    await page.getByRole("button", { name: /suspend user/i }).click();
    await page.getByRole("dialog").getByRole("button", { name: /^suspend$/i }).click();
    await page.getByRole("button", { name: /restore user/i }).click();
    await page.goto(`${ADMIN_URL}/audit`);
    await page.getByPlaceholder("Search by user, action, or resource").fill(userId);
    await expect(page.locator("tr[mat-row]").first()).toContainText(LOGIN_EMAIL, { timeout: 5_000 });
  });
});
