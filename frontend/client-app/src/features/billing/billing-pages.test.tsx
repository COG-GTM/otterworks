import { http, HttpResponse, delay } from "msw";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { describe, expect, it } from "vitest";
import BillingChangePlanPage from "./change-plan-page";
import BillingEntitlementPage from "./entitlement-page";
import { billingServer } from "../../test-setup";

const TENANT_A = "00000000-0000-0000-0000-000000000001";
const TENANT_B = "00000000-0000-0000-0000-000000000002";
const PLAN = "10000000-0000-0000-0000-000000000001";

function renderEntitlement(tenantId: string) {
  return render(
    <MemoryRouter initialEntries={[`/billing/entitlement/${tenantId}`]}>
      <TenantSwitcher />
      <Routes>
        <Route path="/billing/entitlement/:tenantId" element={<BillingEntitlementPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function TenantSwitcher() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate(`/billing/entitlement/${TENANT_B}`)}>
      Switch tenant
    </button>
  );
}

function renderChangePlan() {
  return render(
    <MemoryRouter initialEntries={[`/billing/change/${TENANT_A}`]}>
      <ChangeTenantSwitcher />
      <Routes>
        <Route path="/billing/change/:tenantId" element={<BillingChangePlanPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function ChangeTenantSwitcher() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate(`/billing/change/${TENANT_B}`)}>
      Switch change tenant
    </button>
  );
}

describe("Billing page state transitions", () => {
  it("clears the previous tenant entitlement while switching tenants", async () => {
    billingServer.use(
      http.get("http://localhost:3000/billing-api/api/tenants/:tenantId/entitlement", async ({ params }) => {
        if (params.tenantId === TENANT_B) await delay(100);
        return HttpResponse.json({
          tenant_id: params.tenantId,
          plan_code: params.tenantId === TENANT_A ? "STARTER" : "GROWTH",
          tier: params.tenantId === TENANT_A ? "starter" : "growth",
          monthly_fee: params.tenantId === TENANT_A ? "49.00" : "149.00",
          included_units: params.tenantId === TENANT_A ? 100 : 500,
          subscription_status: "active",
          effective_on: "2026-02-28",
        });
      }),
    );
    renderEntitlement(TENANT_A);
    expect(await screen.findByText("STARTER")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Switch tenant" }));
    await waitFor(() => {
      expect(screen.queryByText("STARTER")).not.toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent("Loading entitlement");
    });
    expect(await screen.findByText("GROWTH")).toBeInTheDocument();
  });

  it("clears a previous success when a later plan submission fails", async () => {
    let attempts = 0;
    let planLoads = 0;
    billingServer.use(
      http.get("http://localhost:3000/billing-api/api/plans", async () => {
        planLoads += 1;
        if (planLoads > 1) await delay(100);
        return HttpResponse.json([
          {
            plan_id: PLAN,
            code: "STARTER",
            tier: "starter",
            monthly_fee: "49.00",
            included_units: 100,
            overage_rate: "0.055000",
          },
        ]);
      }),
      http.post("http://localhost:3000/billing-api/api/tenants/:tenantId/plan-change", () => {
        attempts += 1;
        return attempts === 1
          ? HttpResponse.json({
              latest_plan: PLAN,
              latest_start: "2026-03-01",
              subscriptions: [],
            })
          : HttpResponse.json(
              { detail: "this plan change has already been requested" },
              { status: 409 },
            );
      }),
    );
    renderChangePlan();
    await screen.findByRole("button", { name: "Save plan change" });
    fireEvent.click(screen.getByRole("button", { name: "Save plan change" }));
    expect(await screen.findByText("Plan change saved for 2026-03-01.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Switch change tenant" }));
    await waitFor(() =>
      expect(screen.queryByText("Plan change saved for 2026-03-01.")).not.toBeInTheDocument(),
    );
    await screen.findByRole("button", { name: "Save plan change" });
    fireEvent.click(screen.getByRole("button", { name: "Save plan change" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This plan change was already submitted.",
    );
    await waitFor(() =>
      expect(screen.queryByText("Plan change saved for 2026-03-01.")).not.toBeInTheDocument(),
    );
  });
});
