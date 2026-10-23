import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { loginUser, uniqueEmail } from "./fixtures/test-helpers";

/**
 * QA audit: notification-service primary flows (share -> notification -> read,
 * mark all read, notification preferences). Findings (NS-*) are documented in
 * docs/qa/notification-service.md.
 */

const API = process.env.OTTERWORKS_API_BASE_URL || "http://localhost:8080";
const PASSWORD = "Passw0rd!23";

interface User {
  id: string;
  email: string;
  token: string;
}

async function register(request: APIRequestContext, prefix: string): Promise<User> {
  const email = uniqueEmail().replace("test-", `${prefix}-`);
  const res = await request.post(`${API}/api/v1/auth/register`, {
    data: { email, password: PASSWORD, displayName: `QA ${prefix}` },
  });
  expect(res.status(), await res.text()).toBe(201);
  const body = await res.json();
  return { id: body.user.id, email, token: body.accessToken };
}

const auth = (u: User) => ({ Authorization: `Bearer ${u.token}` });

async function uploadFile(request: APIRequestContext, owner: User, name: string): Promise<string> {
  const res = await request.post(`${API}/api/v1/files/upload`, {
    headers: auth(owner),
    multipart: { file: { name, mimeType: "text/plain", buffer: Buffer.from("qa notification e2e") } },
  });
  expect(res.status(), await res.text()).toBe(201);
  return (await res.json()).file.id;
}

async function shareViaApi(request: APIRequestContext, owner: User, recipient: User, fileId: string) {
  const res = await request.post(`${API}/api/v1/files/${fileId}/share`, {
    headers: auth(owner),
    data: { shared_with: recipient.id, permission: "viewer", shared_by: owner.id },
  });
  expect([200, 201]).toContain(res.status());
}

async function unreadCount(request: APIRequestContext, user: User): Promise<number> {
  const res = await request.get(`${API}/api/v1/notifications/unread-count`, { headers: auth(user) });
  return (await res.json()).unreadCount;
}

async function waitForUnread(request: APIRequestContext, user: User, expected: number) {
  await expect.poll(() => unreadCount(request, user), { timeout: 45_000 }).toBe(expected);
}

async function signIn(page: Page, user: User) {
  await loginUser(page, user.email, PASSWORD);
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
}

test.describe("QA notification-service", () => {
  test.setTimeout(120_000);

  test("sharing a file from the UI notifies the recipient (bell + notifications page)", async ({ page, request }) => {
    const owner = await register(request, "qa-owner");
    const recipient = await register(request, "qa-recipient");
    const fileName = `qa-share-${Date.now()}.txt`;
    await uploadFile(request, owner, fileName);

    await signIn(page, owner);
    await page.goto("/files");
    const card = page.getByText(fileName).first();
    await expect(card).toBeVisible({ timeout: 15_000 });
    const fileCard = card.locator("xpath=ancestor::*[.//button[@aria-label='Star']][1]");
    await fileCard.hover();
    await fileCard.locator("button:not([aria-label])").first().click();
    await page.getByRole("button", { name: "Share", exact: true }).first().click();
    await page.getByPlaceholder("Add people by email").fill(recipient.email);
    await page.getByRole("button", { name: "Share", exact: true }).last().click();
    await expect(page.getByText(recipient.email).first()).toBeVisible({ timeout: 15_000 });

    await waitForUnread(request, recipient, 1);

    await page.context().clearCookies();
    await page.evaluate(() => localStorage.clear());
    await signIn(page, recipient);
    await page.goto("/notifications");
    await expect(page.getByText("File Shared With You").first()).toBeVisible();
    await expect(page.getByText("1 unread notification")).toBeVisible();
  });

  test("bell shows the unread badge after a share", async ({ page, request }) => {
    test.fail(true, "FINDING NS-9: NotificationBell reads `count` but unread-count returns `unreadCount`");
    const owner = await register(request, "qa-owner");
    const recipient = await register(request, "qa-recipient");
    await shareViaApi(request, owner, recipient, await uploadFile(request, owner, "bell.txt"));
    await waitForUnread(request, recipient, 1);

    await signIn(page, recipient);
    const bell = page.getByRole("link", { name: "Notifications (1 unread)" });
    await expect(bell).toBeVisible({ timeout: 15_000 });
    await bell.click();
    await expect(page).toHaveURL(/\/notifications/);
  });

  test("clicking a notification marks it read", async ({ page, request }) => {
    // FINDING NS-6: client-app sends PATCH /notifications/{id}/read, backend only routes PUT,
    // so the read state never persists. Remove test.fail() once fixed.
    test.fail(true, "FINDING NS-6: PATCH /notifications/{id}/read is not routed by notification-service");
    const owner = await register(request, "qa-owner");
    const recipient = await register(request, "qa-recipient");
    await shareViaApi(request, owner, recipient, await uploadFile(request, owner, "read-one.txt"));
    await waitForUnread(request, recipient, 1);

    await signIn(page, recipient);
    await page.goto("/notifications");
    await page.getByText("File Shared With You").first().click();
    await waitForUnread(request, recipient, 0);
    await page.reload();
    await expect(page.getByText(/unread notification/)).toHaveCount(0);
  });

  test("mark all as read clears the unread badge", async ({ page, request }) => {
    test.fail(true, "FINDING NS-6: POST /notifications/read-all is not routed by notification-service");
    const owner = await register(request, "qa-owner");
    const recipient = await register(request, "qa-recipient");
    await shareViaApi(request, owner, recipient, await uploadFile(request, owner, "all-1.txt"));
    await shareViaApi(request, owner, recipient, await uploadFile(request, owner, "all-2.txt"));
    await waitForUnread(request, recipient, 2);

    await signIn(page, recipient);
    await page.goto("/notifications");
    await expect(page.getByText("2 unread notifications")).toBeVisible();
    await page.getByRole("button", { name: "Mark all as read" }).click();
    await waitForUnread(request, recipient, 0);
    await page.reload();
    await expect(page.getByRole("link", { name: "Notifications", exact: true })).toBeVisible();
  });

  test("notification preference toggles persist across reload", async ({ page, request }) => {
    const user = await register(request, "qa-prefs");
    await signIn(page, user);
    await page.goto("/settings");
    await expect(page.getByRole("heading", { name: "Notification preferences" })).toBeVisible();

    const toggle = (label: string) =>
      page.locator("div.flex.items-center.justify-between", { hasText: label }).getByRole("button");
    const desktop = toggle("Desktop notifications");
    const inApp = toggle("In-app notifications");
    await expect(desktop).toHaveClass(/bg-gray-300/);
    await expect(inApp).toHaveClass(/bg-otter-600/);

    const saved = page.waitForResponse((r) => r.url().includes("/settings") && r.request().method() === "PATCH");
    await desktop.click();
    expect((await saved).ok()).toBeTruthy();
    const saved2 = page.waitForResponse((r) => r.url().includes("/settings") && r.request().method() === "PATCH");
    await inApp.click();
    expect((await saved2).ok()).toBeTruthy();

    await page.reload();
    await expect(toggle("Desktop notifications")).toHaveClass(/bg-otter-600/);
    await expect(toggle("In-app notifications")).toHaveClass(/bg-gray-300/);
  });

  test("notification-service preferences persist (API, as used by delivery)", async ({ request }) => {
    const user = await register(request, "qa-svc-prefs");
    const put = await request.put(`${API}/api/v1/preferences`, {
      headers: auth(user),
      data: { userId: user.id, eventType: "file_shared", channels: ["IN_APP"] },
    });
    expect(put.status()).toBe(204);
    const get = await request.get(`${API}/api/v1/preferences`, { headers: auth(user) });
    expect((await get.json()).channels.file_shared).toEqual(["IN_APP"]);
  });
});
