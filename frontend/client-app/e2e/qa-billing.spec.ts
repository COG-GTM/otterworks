import { test, expect, type APIRequestContext } from "@playwright/test";

// QA audit (billing unit). Needs the procs stack (`make procs-up NS=dev`) and, for the portal
// block, legacy-portal on :8095. Each block skips itself when its backend is unreachable.
const LEGACY_BILLING = process.env.QA_LEGACY_BILLING_URL ?? "http://localhost:8109";
const BILLING_SERVICE = process.env.QA_BILLING_SERVICE_URL ?? "http://localhost:12109";
const LEGACY_PORTAL = process.env.QA_LEGACY_PORTAL_URL ?? "http://localhost:8095";

const TENANT_1 = "00000000-0000-0000-0000-000000000001";
const TENANT_6 = "00000000-0000-0000-0000-000000000006";
const GROWTH = "10000000-0000-0000-0000-000000000002";

type Plan = { plan_id: string; code: string; monthly_fee: string; included_units: number };

async function reachable(request: APIRequestContext, url: string): Promise<boolean> {
  try {
    return (await request.get(url, { timeout: 5_000 })).ok();
  } catch {
    return false;
  }
}

test.describe("Billing fixture (client-app -> billing-service)", () => {
  // Every test resets the shared billing-service database, so they must not interleave.
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ request }) => {
    test.skip(!(await reachable(request, `${BILLING_SERVICE}/health`)), "billing-service down");
    const reset = await request.post(`${BILLING_SERVICE}/internal/reset`);
    expect(reset.status()).toBe(204);
  });

  test("plans page matches billing-service and legacy catalog", async ({ page, request }) => {
    const target = (await (await request.get(`${BILLING_SERVICE}/api/plans`)).json()) as Plan[];
    const legacy = (await (await request.get(`${LEGACY_BILLING}/plans`)).json()) as Plan[];
    expect(target.map((p) => [p.code, p.monthly_fee])).toEqual(legacy.map((p) => [p.code, p.monthly_fee]));

    await page.goto("/billing/plans");
    const cards = page.getByRole("list", { name: "Available plans" }).getByRole("listitem");
    await expect(cards).toHaveCount(target.length);
    for (const [index, plan] of target.entries()) {
      await expect(cards.nth(index).getByRole("heading")).toHaveText(plan.code);
      await expect(cards.nth(index)).toContainText(`$${plan.monthly_fee}`);
      await expect(cards.nth(index)).toContainText(`${plan.included_units} included units`);
    }
  });

  test("entitlement page matches legacy entitlement JSON", async ({ page, request }) => {
    const [legacy] = await (await request.get(`${LEGACY_BILLING}/plans/${TENANT_1}/entitlement?on=2026-02-28`)).json();
    await page.goto(`/billing/entitlement/${TENANT_1}`);
    const section = page.getByRole("region", { name: "Tenant entitlement" });
    await expect(section.getByRole("heading", { level: 2 })).toHaveText(legacy.plan_code);
    await expect(section).toContainText(legacy.tier);
    await expect(section).toContainText(legacy.subscription_status);
    await expect(section).toContainText(String(legacy.included_units));
  });

  test("entitlement page rejects a malformed tenant id", async ({ page }) => {
    await page.goto("/billing/entitlement/not-a-uuid");
    await expect(page.getByText("A valid tenant id is required.").first()).toBeVisible();
  });

  test("change plan saves once and reports duplicates", async ({ page, request }) => {
    await page.goto(`/billing/change/${TENANT_1}`);
    await page.getByLabel("Plan").selectOption({ label: "GROWTH" });
    await page.getByLabel("Effective date").fill("2026-03-01");
    await page.getByRole("button", { name: "Save plan change" }).click();
    await expect(page.getByText("Plan change saved for 2026-03-01.")).toBeVisible();

    await page.getByRole("button", { name: "Save plan change" }).click();
    await expect(page.getByText("This plan change was already submitted.").first()).toBeVisible();

    const after = await (await request.get(`${BILLING_SERVICE}/api/tenants/${TENANT_1}/entitlement?on=2026-03-01`)).json();
    expect(after.plan_code).toBe("GROWTH");
    expect(after.subscription_status).toBe("active");
  });
});

test.describe("Legacy billing server-rendered pages", () => {
  test.beforeEach(async ({ request }) => {
    test.skip(!(await reachable(request, `${LEGACY_BILLING}/health`)), "legacy-billing down");
  });

  test("index lists the same plans as /plans JSON", async ({ page, request }) => {
    const plans = (await (await request.get(`${LEGACY_BILLING}/plans`)).json()) as Plan[];
    await page.goto(`${LEGACY_BILLING}/`);
    const items = page.getByRole("listitem");
    await expect(items).toHaveCount(plans.length);
    for (const [index, plan] of plans.entries()) {
      await expect(items.nth(index)).toHaveText(`${plan.code} — ${plan.monthly_fee} / ${plan.included_units} units`);
    }
  });

  test("legacy change-plan form post lands on the new entitlement", async ({ page }) => {
    const effective = `2032-0${1 + Math.floor(Math.random() * 9)}-${10 + Math.floor(Math.random() * 18)}`;
    await page.goto(`${LEGACY_BILLING}/`);
    const response = await page.request.post(`${LEGACY_BILLING}/plans/${TENANT_6}/change`, {
      form: { plan_id: GROWTH, effective_on: effective },
      maxRedirects: 0,
    });
    expect(response.status()).toBe(302);
    await page.goto(`${LEGACY_BILLING}${response.headers()["location"].replace(/^https?:\/\/[^/]+/, "")}`);
    await expect(page.locator("body")).toContainText('"plan_code":"GROWTH"');
  });

  test("invoice preview then issue for the same tenant", async ({ page, request }) => {
    await page.goto(`${LEGACY_BILLING}/api/invoices/${TENANT_6}/preview?period_start=2026-02-01&period_end=2026-02-28`);
    const body = await page.locator("body").innerText();
    const lines = JSON.parse(body) as { line_type: string; amount: string }[];
    expect(lines.map((l) => l.line_type)).toEqual(["plan", "usage", "tax", "tax", "credit"]);
    const issue = await request.post(`${LEGACY_BILLING}/api/invoices/${TENANT_6}/issue`, {
      form: { period_start: "2026-02-01", period_end: "2026-02-28" },
    });
    expect(await issue.json()).toEqual({ status: "issued" });
  });
});

test.describe("Legacy portal", () => {
  test.beforeEach(async ({ request }) => {
    test.skip(!(await reachable(request, `${LEGACY_PORTAL}/health`)), "legacy-portal down");
  });

  test("health banner and announcement publish flow", async ({ page, request }) => {
    await page.goto(`${LEGACY_PORTAL}/health`);
    await expect(page.locator("body")).toContainText("OtterWorks Portal (on-prem)");

    const title = `qa-e2e-${Date.now()}`;
    const created = await request.post(`${LEGACY_PORTAL}/api/announcements`, {
      data: { title, body: "from playwright", published: false },
    });
    expect(created.status()).toBe(201);
    const { id } = await created.json();
    await page.goto(`${LEGACY_PORTAL}/api/announcements`);
    await expect(page.locator("body")).not.toContainText(title);
    expect((await request.post(`${LEGACY_PORTAL}/api/announcements/${id}/publish`)).ok()).toBeTruthy();
    await page.reload();
    await expect(page.locator("body")).toContainText(title);
  });
});
