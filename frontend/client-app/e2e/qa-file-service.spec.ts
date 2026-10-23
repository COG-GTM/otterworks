import fs from "node:fs";
import { test, expect, type Page, type APIRequestContext } from "@playwright/test";
import { registerUser, expectDashboard, loginUser, uniqueEmail } from "./fixtures/test-helpers";

/**
 * QA e2e for file-service (docs/qa/file-service.md). Requires the core stack
 * (web on BASE_URL, gateway on QA_API_URL). The web app has no "move" UI and
 * stars live in localStorage, so move is driven through the gateway API and
 * starring is verified on the Starred page only for the same browser.
 */
const API = process.env.QA_API_URL || "http://localhost:8080";
const PASSWORD = "Passw0rd!23";

async function apiRegister(request: APIRequestContext, prefix: string) {
  const email = uniqueEmail().replace("test-", `${prefix}-`);
  const res = await request.post(`${API}/api/v1/auth/register`, {
    data: { email, password: PASSWORD, displayName: `QA ${prefix}` },
  });
  expect(res.status(), await res.text()).toBe(201);
  const body = await res.json();
  return { email, id: body.user.id as string, token: body.accessToken as string };
}

async function token(page: Page) {
  return page.evaluate(() => localStorage.getItem("otter_access_token"));
}

function card(page: Page, name: string) {
  // Innermost element containing both the item name and its star toggle.
  return page
    .locator("div")
    .filter({ has: page.getByText(name, { exact: true }) })
    .filter({ has: page.getByRole("button", { name: /^(Star|Unstar)$/ }) })
    .last();
}

async function uploadViaUi(page: Page, name: string, content: string) {
  await page.goto("/files");
  await expect(page.getByRole("heading", { name: "Files" })).toBeVisible();
  await page.getByRole("button", { name: /^Upload/ }).first().click();
  await page.locator('input[type="file"]').first().setInputFiles({
    name,
    mimeType: "text/plain",
    buffer: Buffer.from(content),
  });
  await expect(page.getByText(name, { exact: true }).first()).toBeVisible({ timeout: 20_000 });
}

test.describe("QA file-service: primary flows", () => {
  test.describe.configure({ mode: "serial" });

  test("upload, detail, download, folder+move, star, share, trash/restore, Recent/Starred/Shared/Trash", async ({
    page,
    browser,
    request,
  }) => {
    test.setTimeout(180_000);
    const stamp = Date.now().toString(36);
    const fileName = `qa-report-${stamp}.txt`;
    const folderName = `QA Folder ${stamp}`;
    const content = `otterworks qa ${stamp}`;
    const friend = await apiRegister(request, "qa-friend");

    await registerUser(page, { name: "QA Owner", password: PASSWORD });
    await expectDashboard(page);

    // Upload
    await uploadViaUi(page, fileName, content);
    await page.goto("/files");

    // Create a folder
    await page.getByRole("button", { name: "New folder" }).click();
    await page.getByPlaceholder("Folder name").fill(folderName);
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await expect(page.getByText(folderName, { exact: true })).toBeVisible();

    // Star the file (client-side, localStorage)
    await card(page, fileName).getByRole("button", { name: "Star" }).click();
    await expect(card(page, fileName).getByRole("button", { name: "Unstar" })).toBeVisible();

    // Open file detail
    await page.getByText(fileName, { exact: true }).click();
    await expect(page).toHaveURL(/\/files\/[0-9a-f-]{36}$/);
    const fileId = page.url().split("/").pop()!;
    await expect(page.getByRole("heading", { name: fileName })).toBeVisible();

    // Download: the button resolves a presigned URL; the bytes behind it match.
    // (Clicking it currently navigates the tab to the raw object, FS-14, so
    // return to the detail page afterwards.)
    await page.getByRole("button", { name: "Download" }).first().click();
    await page.goto(`/files/${fileId}`);
    const presigned = (await (await request.get(`${API}/api/v1/files/${fileId}/download`, {
      headers: { Authorization: `Bearer ${await token(page)}` },
    })).json()).url as string;
    const blob = await request.get(presigned.replace("://localstack:", "://localhost:"));
    expect(await blob.text()).toBe(content);

    // Share with a second user from the detail page
    await page.getByRole("button", { name: "Share", exact: true }).first().click();
    await page.getByPlaceholder("Add people by email").fill(friend.email);
    await page.getByRole("button", { name: "Share", exact: true }).last().click();
    await expect(page.getByText(friend.email).first()).toBeVisible({ timeout: 15_000 });
    await page.keyboard.press("Escape");

    // Move into the folder (no move UI exists; use the gateway as the client would)
    const auth = { Authorization: `Bearer ${await token(page)}` };
    const folders = await (await request.get(`${API}/api/v1/folders`, { headers: auth })).json();
    const folder = folders.folders.find((f: { name: string }) => f.name === folderName);
    const moved = await request.put(`${API}/api/v1/files/${fileId}/move`, {
      headers: auth,
      data: { folder_id: folder.id },
    });
    expect(moved.status()).toBe(200);
    await page.goto(`/files?folder=${folder.id}`);
    await expect(page.getByText(fileName, { exact: true })).toBeVisible();

    // Trash from the detail page, then restore from Trash
    await page.goto(`/files/${fileId}`);
    await page.getByRole("button", { name: "Delete" }).click();
    await expect(page.getByText("File moved to trash")).toBeVisible();
    await page.goto("/trash");
    await expect(page.getByRole("heading", { name: "Trash" })).toBeVisible();
    await expect(page.getByText(fileName, { exact: true })).toBeVisible();
    await page
      .locator("div")
      .filter({ has: page.getByText(fileName, { exact: true }) })
      .filter({ has: page.getByRole("button", { name: "Restore" }) })
      .last()
      .getByRole("button", { name: "Restore" })
      .click();
    await expect(page.getByText(fileName, { exact: true })).toHaveCount(0, { timeout: 15_000 });

    // Recent + Starred show the restored file
    await page.goto("/recent");
    await expect(page.getByRole("heading", { name: "Recent" })).toBeVisible();
    await expect(page.getByText(fileName, { exact: true }).first()).toBeVisible();
    await page.goto("/starred");
    await expect(page.getByRole("heading", { name: "Starred" })).toBeVisible();
    await expect(page.getByText(fileName, { exact: true }).first()).toBeVisible();

    // Shared with me, as the recipient
    const friendContext = await browser.newContext();
    const friendPage = await friendContext.newPage();
    await loginUser(friendPage, friend.email, PASSWORD);
    await expectDashboard(friendPage);
    await friendPage.goto("/shared");
    await expect(friendPage.getByRole("heading", { name: "Shared with me" })).toBeVisible();
    await expect(friendPage.getByText(fileName, { exact: true }).first()).toBeVisible();
    await friendContext.close();
  });

  test("oversize upload is rejected client-side before reaching file-service", async ({ page }) => {
    await registerUser(page, { password: PASSWORD });
    await expectDashboard(page);
    await page.goto("/files");
    await page.getByRole("button", { name: /^Upload/ }).first().click();
    const bigFile = test.info().outputPath("too-big.bin");
    fs.writeFileSync(bigFile, Buffer.alloc(100 * 1024 * 1024 + 1));
    await page.locator('input[type="file"]').first().setInputFiles(bigFile);
    await expect(page.getByText(/File too large/).first()).toBeVisible();
  });

  test.fail("FS-01: another user's file detail must not be readable by URL", async ({ page, request }) => {
    const alice = await apiRegister(request, "qa-alice");
    const upload = await request.post(`${API}/api/v1/files/upload`, {
      headers: { Authorization: `Bearer ${alice.token}` },
      multipart: { file: { name: "alice-private.txt", mimeType: "text/plain", buffer: Buffer.from("secret") } },
    });
    const fileId = (await upload.json()).file.id;

    await registerUser(page, { password: PASSWORD });
    await expectDashboard(page);
    await page.goto(`/files/${fileId}`);
    await expect(page.getByText("File not found")).toBeVisible();
  });

  test.fail("FS-14: Download must save the file, not navigate the app tab to the raw object", async ({ page }) => {
    const name = `qa-dl-${Date.now().toString(36)}.txt`;
    await registerUser(page, { password: PASSWORD });
    await expectDashboard(page);
    await uploadViaUi(page, name, "download me");
    await page.getByText(name, { exact: true }).first().click();
    await expect(page).toHaveURL(/\/files\/[0-9a-f-]{36}$/);
    const download = page.waitForEvent("download", { timeout: 10_000 });
    await page.getByRole("button", { name: "Download" }).first().click();
    expect((await download).suggestedFilename()).toBe(name);
  });
});
