import { test, expect, type Page } from "@playwright/test";
import { registerUser, expectDashboard } from "./fixtures/test-helpers";

// QA audit of document-service primary flows; see docs/qa/document-service.md.

const editor = (page: Page) => page.locator(".ProseMirror");

async function accessToken(page: Page): Promise<string> {
  const token = await page.evaluate(() => localStorage.getItem("otter_access_token"));
  expect(token, "access token after registration").toBeTruthy();
  return token as string;
}

function waitForPatch(page: Page, id: string) {
  return page.waitForResponse(
    (r) => r.url().includes(`/api/v1/documents/${id}`) && r.request().method() === "PATCH" && r.ok()
  );
}

test.describe("QA document-service: documents", () => {
  test.beforeEach(async ({ page }) => {
    await registerUser(page, { name: "QA Doc User" });
    await expectDashboard(page);
  });

  test("blank document: create, edit, save, reload, rename, delete", async ({ page }) => {
    await page.goto("/documents");
    const created = page.waitForResponse(
      (r) => /\/api\/v1\/documents\/?$/.test(new URL(r.url()).pathname) && r.request().method() === "POST"
    );
    await page.getByRole("button", { name: "New document" }).first().click();
    const createdRes = await created;
    expect(createdRes.status()).toBe(201);
    const { id } = await createdRes.json();
    await expect(page).toHaveURL(new RegExp(`/documents/${id}$`));
    await expect(page.getByRole("button", { name: "Untitled document" })).toBeVisible();

    const body = `QA persisted body ${Date.now()}`;
    await editor(page).click();
    await page.keyboard.type(body);
    const saved = waitForPatch(page, id);
    await page.getByRole("button", { name: "Save" }).click();
    await saved;

    await page.reload();
    await expect(editor(page)).toContainText(body, { timeout: 15_000 });

    const newTitle = `QA Renamed ${Date.now()}`;
    await page.getByRole("button", { name: "Untitled document" }).click();
    const titleInput = page.locator("h1 + input, input.text-xl").first();
    await titleInput.fill(newTitle);
    const renamed = waitForPatch(page, id);
    await titleInput.press("Enter");
    await renamed;

    await page.reload();
    await expect(page.getByRole("button", { name: newTitle })).toBeVisible();
    await expect(editor(page)).toContainText(body, { timeout: 15_000 });

    await page.goto("/documents");
    await expect(page.getByText(newTitle)).toBeVisible();

    await page.goto(`/documents/${id}`);
    const deleted = page.waitForResponse(
      (r) => r.url().includes(`/api/v1/documents/${id}`) && r.request().method() === "DELETE"
    );
    await page.locator("button:has(svg[class*=\"lucide-trash\"])").click();
    expect((await deleted).status()).toBe(204);
    await expect(page).toHaveURL(/\/documents$/);
    await expect(page.getByText(newTitle)).toHaveCount(0);
  });

  test("document from template opens in the editor with template content", async ({ page }) => {
    // The client app has no template picker (finding DOC-QA-14), so the template and
    // the from-template document are created via the gateway and verified in the UI.
    const token = await accessToken(page);
    const headers = { Authorization: `Bearer ${token}` };
    const sub = JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString()).sub as string;
    const marker = `Template body ${Date.now()}`;

    const tpl = await page.request.post("/api/v1/templates/", {
      headers,
      data: { name: "QA Template", description: "qa", content: `<p>${marker}</p>`, created_by: sub },
    });
    expect(tpl.status()).toBe(201);
    const template = await tpl.json();

    const doc = await page.request.post(`/api/v1/documents/from-template/${template.id}`, {
      headers,
      data: { title: "QA From Template", owner_id: sub },
    });
    expect(doc.status()).toBe(201);
    const { id } = await doc.json();

    await page.goto("/documents");
    await page.getByText("QA From Template").first().click();
    await expect(page).toHaveURL(new RegExp(`/documents/${id}$`));
    await expect(editor(page)).toContainText(marker, { timeout: 15_000 });

    await editor(page).click();
    await page.keyboard.press("End");
    await page.keyboard.type(" edited");
    const saved = waitForPatch(page, id);
    await page.getByRole("button", { name: "Save" }).click();
    await saved;
    await page.reload();
    await expect(editor(page)).toContainText(`${marker} edited`, { timeout: 15_000 });
  });

  test("another user cannot open my document", async ({ page, browser }) => {
    await page.goto("/documents");
    const created = page.waitForResponse(
      (r) => /\/api\/v1\/documents\/?$/.test(new URL(r.url()).pathname) && r.request().method() === "POST"
    );
    await page.getByRole("button", { name: "New document" }).first().click();
    const { id } = await (await created).json();

    const context = await browser.newContext();
    const other = await context.newPage();
    await registerUser(other, { name: "QA Intruder" });
    await expectDashboard(other);
    await other.goto(`/documents/${id}`);
    await expect(other.getByText("Document not found")).toBeVisible({ timeout: 15_000 });
    await context.close();
  });
});
