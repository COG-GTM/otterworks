import { http, HttpResponse } from "msw";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import BillingDunningPage from "./dunning-page";
import BillingInvoicesPage from "./invoices-page";
import { billingServer } from "../../test-setup";

const API = "http://localhost:3000/billing-api/api";
const TENANT = "00000000-0000-0000-0000-000000000006";
const INVOICE = "109bb68d-8fc1-401b-9a8a-fa89e98e2388";

const rating = {
  tenant_id: TENANT,
  period_start: "2026-02-01",
  period_end: "2026-02-28",
  used_units: 201,
  quota_units: 100,
  rollover_units: 0,
  billable_units: 101,
  first_tier_units: 101,
  second_tier_units: 0,
  overage_amount: "5.56",
};

const preview = [
  { line_no: 1, line_type: "plan", description: "STARTER", amount: "49.00", tax_amount: "0", credit_applied: "0", total: "49.00" },
  { line_no: 3, line_type: "tax", description: "regional tax", amount: "2.2506", tax_amount: "0", credit_applied: "0", total: "2.2506" },
];

function renderInvoices() {
  return render(
    <MemoryRouter initialEntries={[`/billing/invoices/${TENANT}`]}>
      <Routes>
        <Route path="/billing/invoices/:tenantId" element={<BillingInvoicesPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function useInvoiceHandlers(requests: string[]) {
  billingServer.use(
    http.get(`${API}/tenants/:tenantId/usage-rating`, ({ request }) => {
      requests.push(new URL(request.url).search);
      return HttpResponse.json(rating);
    }),
    http.get(`${API}/tenants/:tenantId/usage-summary`, () =>
      HttpResponse.json([{ kind: "api", event_count: 2, units: 201 }]),
    ),
    http.get(`${API}/tenants/:tenantId/invoice-preview`, () => HttpResponse.json(preview)),
  );
}

describe("Billing usage and invoices page", () => {
  it("shows rating, usage summary and preview for the selected period", async () => {
    const requests: string[] = [];
    useInvoiceHandlers(requests);
    renderInvoices();

    const ratingSection = await screen.findByRole("region", { name: "Usage rating" });
    expect(within(ratingSection).getByText("201", { selector: "dd" })).toBeInTheDocument();
    expect(within(ratingSection).getByText("5.56")).toBeInTheDocument();
    expect(within(ratingSection).getByText("api")).toBeInTheDocument();
    const previewSection = screen.getByRole("region", { name: "Invoice preview" });
    expect(within(previewSection).getByText("2.25")).toBeInTheDocument();
    expect(requests[0]).toBe("?period_start=2026-02-01&period_end=2026-02-28");

    fireEvent.change(screen.getByLabelText("Period start"), { target: { value: "2026-03-01" } });
    fireEvent.change(screen.getByLabelText("Period end"), { target: { value: "2026-03-31" } });
    fireEvent.click(screen.getByRole("button", { name: "Load period" }));
    await waitFor(() =>
      expect(requests.at(-1)).toBe("?period_start=2026-03-01&period_end=2026-03-31"),
    );
  });

  it("finalizes rating and issues an invoice, then reads its persisted lines", async () => {
    const bodies: unknown[] = [];
    useInvoiceHandlers([]);
    billingServer.use(
      http.post(`${API}/tenants/:tenantId/rating-periods`, async ({ request }) => {
        bodies.push(await request.json());
        const result = { used_units: 201, quota_units: 100, rollover_units: 0, billable_units: 101, overage_amount: "5.56" };
        return HttpResponse.json({ period_id: "p", result, rating_results: [result] });
      }),
      http.post(`${API}/tenants/:tenantId/invoices`, async ({ request }) => {
        bodies.push(await request.json());
        const invoice = { status: "issued", subtotal: "54.56", tax: "4.50", total: "59.06" };
        return HttpResponse.json({ invoice_id: INVOICE, invoice, invoices: [invoice], lines: [], credit_notes: [] });
      }),
      http.get(`${API}/invoices/:invoiceId/lines`, ({ params }) => {
        expect(params.invoiceId).toBe(INVOICE);
        return HttpResponse.json([
          { line_no: 1, line_type: "plan", description: "STARTER", amount: "49.00" },
          { line_no: 2, line_type: "usage", description: "usage overage", amount: "5.56" },
        ]);
      }),
    );
    renderInvoices();

    fireEvent.click(await screen.findByRole("button", { name: "Finalize rating" }));
    expect(await screen.findByText(/Rating finalized: 101 billable units/)).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: "Issue invoice" }));
    const issued = await screen.findByRole("region", { name: "Issued invoice" });
    expect(within(issued).getByText("59.06")).toBeInTheDocument();
    expect(await within(issued).findByText("usage overage")).toBeInTheDocument();
    expect(bodies).toEqual([
      { period_start: "2026-02-01", period_end: "2026-02-28" },
      { period_start: "2026-02-01", period_end: "2026-02-28" },
    ]);
  });

  it("explains when no subscription covers the period", async () => {
    billingServer.use(
      http.get(`${API}/tenants/:tenantId/usage-rating`, () => new HttpResponse(null, { status: 404 })),
      http.get(`${API}/tenants/:tenantId/usage-summary`, () => HttpResponse.json([])),
      http.get(`${API}/tenants/:tenantId/invoice-preview`, () => new HttpResponse(null, { status: 404 })),
    );
    renderInvoices();
    expect(await screen.findByRole("alert")).toHaveTextContent("No subscription covers this period.");
  });
});

describe("Billing dunning page", () => {
  it("lists overdue accounts, schedules dunning and suspends tenants", async () => {
    const asOfs: string[] = [];
    billingServer.use(
      http.get(`${API}/dunning/overdue`, ({ request }) => {
        asOfs.push(new URL(request.url).searchParams.get("as_of") ?? "");
        return HttpResponse.json([
          { tenant_id: "00000000-0000-0000-0000-000000000005", invoice_id: "60000000-0000-0000-0000-000000000001", total: "120.00", days_overdue: 30, tenant_status: "active" },
        ]);
      }),
      http.post(`${API}/dunning/schedule`, async ({ request }) => {
        expect(await request.json()).toEqual({ as_of: "2026-02-28" });
        return HttpResponse.json({
          scheduled_for: "2026-03-02",
          scheduled: [{ invoice_id: "60000000-0000-0000-0000-000000000001", attempt_no: 2, scheduled_for: "2026-03-02", status: "scheduled" }],
          attempts: [],
        });
      }),
      http.post(`${API}/dunning/suspend`, () =>
        HttpResponse.json({
          suspended_tenants: ["00000000-0000-0000-0000-000000000005"],
          subscriptions: [],
          suspension_notifications: [{ id: "n", tenant_id: "t", kind: "suspension", sent_at: "2026-02-28T00:00:00Z" }],
        }),
      ),
    );
    render(
      <MemoryRouter>
        <BillingDunningPage />
      </MemoryRouter>,
    );

    const overdue = await screen.findByRole("region", { name: "Overdue accounts" });
    expect(within(overdue).getByText("30")).toBeInTheDocument();
    expect(asOfs).toEqual(["2026-02-28"]);

    fireEvent.click(screen.getByRole("button", { name: "Schedule dunning" }));
    expect(await screen.findByText("Scheduled for 2026-03-02")).toBeInTheDocument();
    expect(screen.getByText(/attempt 2 scheduled/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Suspend overdue accounts" }));
    expect(
      await screen.findByText("Tenant 00000000-0000-0000-0000-000000000005 suspended"),
    ).toBeInTheDocument();
  });
});
