import { test, expect, type APIRequestContext, type Page } from "@playwright/test";

/**
 * QA e2e for search-service (see docs/qa/search-service.md).
 * Users and content are seeded through the API gateway; every assertion about
 * search behaviour is made through the /search page.
 */

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8080";
const INDEX_TIMEOUT = 45_000;
const PLACEHOLDER = "Search files, documents, and folders...";

interface Seeded {
  token: string;
  accessToken: string;
  docTitle: string;
  fileName: string;
}

function uniqueToken(): string {
  return `qa${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

async function registerViaApi(request: APIRequestContext, prefix: string) {
  const email = `${prefix}-${uniqueToken()}@otterworks.test`;
  const res = await request.post(`${GATEWAY_URL}/api/v1/auth/register`, {
    data: { email, password: "OtterworksTest123!", displayName: `${prefix} QA` },
  });
  expect(res.status(), await res.text()).toBe(201);
  const body = await res.json();
  return { id: body.user.id as string, accessToken: body.accessToken as string };
}

async function waitIndexed(request: APIRequestContext, accessToken: string, q: string, count: number) {
  await expect
    .poll(
      async () => {
        const res = await request.get(`${GATEWAY_URL}/api/v1/search/`, {
          params: { q },
          headers: { Authorization: `Bearer ${accessToken}` },
        });
        return res.ok() ? (await res.json()).total : -1;
      },
      { timeout: INDEX_TIMEOUT, intervals: [500, 1000] },
    )
    .toBe(count);
}

async function seedOwner(request: APIRequestContext): Promise<Seeded> {
  const token = uniqueToken();
  const user = await registerViaApi(request, "qa-search-owner");
  const auth = { Authorization: `Bearer ${user.accessToken}` };
  const docTitle = `Otter Ledger ${token}`;
  const fileName = `otter-ledger-${token}.txt`;

  const doc = await request.post(`${GATEWAY_URL}/api/v1/documents/`, {
    headers: auth,
    data: { title: docTitle, content: `Quarterly ${token} figures` },
  });
  expect(doc.status(), await doc.text()).toBe(201);

  const file = await request.post(`${GATEWAY_URL}/api/v1/files/upload`, {
    headers: auth,
    multipart: { file: { name: fileName, mimeType: "text/plain", buffer: Buffer.from("qa search body") } },
  });
  expect(file.status(), await file.text()).toBe(201);

  await waitIndexed(request, user.accessToken, token, 2);
  return { token, accessToken: user.accessToken, docTitle, fileName };
}

async function openSearchAs(page: Page, accessToken: string) {
  await page.addInitScript((t) => localStorage.setItem("otter_access_token", t), accessToken);
  await page.goto("/search");
  await expect(page.getByPlaceholder(PLACEHOLDER)).toBeVisible();
}

async function submitSearch(page: Page, q: string) {
  const input = page.getByPlaceholder(PLACEHOLDER);
  await input.fill(q);
  await input.press("Enter");
}

const results = (page: Page) => page.locator("main a[href^='/documents/'], main a[href^='/files/']");

test.describe("QA search-service: search page", () => {
  let seeded: Seeded;

  test.beforeAll(async ({ request }) => {
    test.setTimeout(INDEX_TIMEOUT + 30_000);
    seeded = await seedOwner(request);
  });

  test("owner finds their new document and file", async ({ page }) => {
    await openSearchAs(page, seeded.accessToken);
    await submitSearch(page, seeded.token);
    await expect(page.getByText(seeded.docTitle)).toBeVisible();
    await expect(page.getByText(seeded.fileName)).toBeVisible();
    await expect(results(page)).toHaveCount(2);
  });

  test("type filters narrow results to documents or files", async ({ page }) => {
    await openSearchAs(page, seeded.accessToken);
    await submitSearch(page, seeded.token);
    await expect(results(page)).toHaveCount(2);

    await page.locator("form button[type='button']").first().click();
    await page.getByRole("button", { name: "Documents", exact: true }).click();
    await expect(page.getByText(seeded.docTitle)).toBeVisible();
    await expect(page.getByText(seeded.fileName)).toHaveCount(0);

    await page.getByRole("button", { name: "Files", exact: true }).click();
    await expect(page.getByText(seeded.fileName)).toBeVisible();
    await expect(page.getByText(seeded.docTitle)).toHaveCount(0);

    await page.getByRole("button", { name: "All types", exact: true }).click();
    await expect(results(page)).toHaveCount(2);
  });

  test("another user never sees the owner's content", async ({ page, request }) => {
    const intruder = await registerViaApi(request, "qa-search-intruder");
    await openSearchAs(page, intruder.accessToken);
    await submitSearch(page, seeded.token);
    await expect(page.getByText("No results found")).toBeVisible();
    await expect(page.getByText(seeded.docTitle)).toHaveCount(0);
    await expect(page.getByText(seeded.fileName)).toHaveCount(0);
  });

  test("empty and no-result states", async ({ page }) => {
    await openSearchAs(page, seeded.accessToken);
    await expect(page.getByText("Search OtterWorks")).toBeVisible();
    await submitSearch(page, `zz-nothing-${uniqueToken()}`);
    await expect(page.getByText("No results found")).toBeVisible();
    await submitSearch(page, '<script>alert(1)</script> "%_*');
    await expect(page.getByText("No results found")).toBeVisible();
  });
});
