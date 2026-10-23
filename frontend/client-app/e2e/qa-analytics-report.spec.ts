import { test, expect, type Page, type APIRequestContext } from "@playwright/test";
import { registerUser, expectDashboard } from "./fixtures/test-helpers";

// QA analytics-report unit (docs/qa/analytics-report.md). The client app has no
// usage-analytics or reports page, so activity/report calls go through the
// signed-in browser session's JWT against the same gateway the SPA uses.
const API = "/api/v1";

async function session(page: Page) {
  const token = await page.evaluate(() => localStorage.getItem("otter_access_token"));
  expect(token, "access token after registration").toBeTruthy();
  const sub = JSON.parse(Buffer.from(token!.split(".")[1], "base64url").toString()).sub as string;
  return { headers: { Authorization: `Bearer ${token}` }, userId: sub };
}

async function waitForReport(request: APIRequestContext, headers: Record<string, string>, id: number) {
  let body: { status: string; fileSizeBytes?: number; errorMessage?: string } = { status: "PENDING" };
  await expect
    .poll(
      async () => {
        body = await (await request.get(`${API}/reports/${id}`, { headers })).json();
        return body.status;
      },
      { timeout: 20_000 }
    )
    .toMatch(/COMPLETED|FAILED/);
  return body;
}

test.describe("QA analytics + reports", () => {
  test.beforeEach(async ({ page }) => {
    await registerUser(page, { name: "QA Analytics" });
    await expectDashboard(page);
  });

  test("document activity shows on dashboard and is tracked by analytics", async ({ page }) => {
    const { headers, userId } = await session(page);
    const title = `QA analytics doc ${Date.now()}`;
    const created = await page.request.post(`${API}/documents/`, {
      headers,
      data: { title, content: "analytics e2e" },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const docId = (await created.json()).id as string;

    await page.reload();
    await expectDashboard(page);
    await expect(page.getByRole("heading", { name: "Recent documents" })).toBeVisible();
    await expect(page.getByText(title).first()).toBeVisible();

    for (const eventType of ["document.created", "document.viewed", "document.edited"]) {
      const r = await page.request.post(`${API}/analytics/events`, {
        headers,
        data: { eventType, userId, resourceId: docId, resourceType: "document" },
      });
      expect(r.status()).toBe(202);
    }
    const activity = await (await page.request.get(`${API}/analytics/users/${userId}/activity`, { headers })).json();
    expect(activity).toMatchObject({ totalEvents: 3, documentsCreated: 1, documentsViewed: 1, documentsEdited: 1 });
    const stats = await (await page.request.get(`${API}/analytics/documents/${docId}/stats`, { headers })).json();
    expect(stats).toMatchObject({ views: 1, edits: 1, uniqueViewers: 1 });
  });

  test("margins analytics widgets render from analytics-service", async ({ page }) => {
    await page.goto("/margins");
    await expect(page.getByRole("heading", { name: "Margins" })).toBeVisible();
    await expect(page.getByText("Gross Margin %")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("margin-chart")).toBeVisible();
    await expect(page.getByTestId("margins-grid").locator("tbody tr").first()).toBeVisible();
  });

  test("storage summary report generates and downloads as CSV", async ({ page }) => {
    const { headers, userId } = await session(page);
    const created = await page.request.post(`${API}/reports`, {
      headers,
      data: { reportName: "QA e2e storage", category: "STORAGE_SUMMARY", reportType: "CSV", requestedBy: userId },
    });
    expect(created.status()).toBe(202);
    const id = (await created.json()).id as number;
    const done = await waitForReport(page.request, headers, id);
    expect(done.status, done.errorMessage).toBe("COMPLETED");

    const download = await page.request.get(`${API}/reports/${id}/download`, { headers });
    expect(download.status()).toBe(200);
    expect(download.headers()["content-type"]).toContain("text/csv");
    expect(download.headers()["content-disposition"]).toContain("attachment");
    expect((await download.body()).length).toBe(done.fileSizeBytes);

    expect((await page.request.delete(`${API}/reports/${id}`, { headers })).status()).toBe(204);
  });

  test("usage analytics report completes (RPT-1)", async ({ page }) => {
    test.fail(true, "RPT-1: USAGE_ANALYTICS reports FAIL with 405 from analytics-service; fallback unreachable");
    const { headers, userId } = await session(page);
    const created = await page.request.post(`${API}/reports`, {
      headers,
      data: { reportName: "QA e2e usage", category: "USAGE_ANALYTICS", reportType: "CSV", requestedBy: userId },
    });
    const done = await waitForReport(page.request, headers, (await created.json()).id);
    expect(done.status).toBe("COMPLETED");
  });
});
