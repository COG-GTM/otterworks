import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { billingApi, BillingApiError } from "./api";
import { billingServer } from "../../test-setup";

const TENANT = "00000000-0000-0000-0000-000000000001";
const PLAN = "10000000-0000-0000-0000-000000000001";

afterEach(() => localStorage.removeItem("otter_access_token"));

describe("billing api client", () => {
  it("sends the platform access token on reads and plan changes", async () => {
    localStorage.setItem("otter_access_token", "platform-token");
    const seen: Array<{ auth: string | null; type: string | null }> = [];
    billingServer.use(
      http.get(
        "http://localhost:3000/billing-api/api/tenants/:tenantId/entitlement",
        ({ request }) => {
          seen.push({ auth: request.headers.get("authorization"), type: null });
          return HttpResponse.json({ tenant_id: TENANT });
        },
      ),
      http.post(
        "http://localhost:3000/billing-api/api/tenants/:tenantId/plan-change",
        ({ request }) => {
          seen.push({
            auth: request.headers.get("authorization"),
            type: request.headers.get("content-type"),
          });
          return HttpResponse.json({
            latest_plan: PLAN,
            latest_start: "2026-03-01",
            subscriptions: [],
          });
        },
      ),
    );

    await billingApi.entitlement(TENANT, "2026-03-01");
    await billingApi.changePlan(TENANT, PLAN, "2026-03-01");

    expect(seen).toEqual([
      { auth: "Bearer platform-token", type: null },
      { auth: "Bearer platform-token", type: "application/json" },
    ]);
  });

  it("omits the header when signed out and surfaces 401", async () => {
    let auth: string | null = "unset";
    billingServer.use(
      http.get("http://localhost:3000/billing-api/api/plans", ({ request }) => {
        auth = request.headers.get("authorization");
        return HttpResponse.json({ detail: "authentication required" }, { status: 401 });
      }),
    );

    const error = await billingApi.listPlans().catch((caught: unknown) => caught);

    expect(auth).toBeNull();
    expect(error).toBeInstanceOf(BillingApiError);
    expect((error as BillingApiError).status).toBe(401);
  });
});
