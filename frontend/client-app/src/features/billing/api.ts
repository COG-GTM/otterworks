export const BILLING_BASE_URL =
  import.meta.env.VITE_BILLING_SERVICE_URL ||
  `${window.location.origin}/billing-api`;

export class BillingApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export type Plan = {
  plan_id: string;
  code: string;
  tier: string;
  monthly_fee: string;
  included_units: number;
  overage_rate: string;
};

export type Entitlement = {
  tenant_id: string;
  plan_code: string;
  tier: string;
  monthly_fee: string;
  included_units: number;
  subscription_status: string;
  effective_on: string;
};

export type Subscription = {
  plan_id: string;
  starts_on: string;
  ends_on: string | null;
  status: string;
};

export type PlanChangeResult = {
  latest_plan: string;
  latest_start: string;
  subscriptions: Subscription[];
};

export type BillingPeriod = { period_start: string; period_end: string };

export type UsageRating = BillingPeriod & {
  tenant_id: string;
  used_units: number;
  quota_units: number;
  rollover_units: number;
  billable_units: number;
  first_tier_units: number;
  second_tier_units: number;
  overage_amount: string;
};

export type UsageKindSummary = { kind: string; event_count: number; units: number };

export type RatingResult = {
  used_units: number;
  quota_units: number;
  rollover_units: number;
  billable_units: number;
  overage_amount: string;
};

export type FinalizedRating = {
  period_id: string;
  result: RatingResult;
  rating_results: RatingResult[];
};

export type InvoicePreviewLine = {
  line_no: number;
  line_type: string;
  description: string;
  amount: string;
  tax_amount: string;
  credit_applied: string;
  total: string;
};

export type InvoiceLine = Pick<InvoicePreviewLine, "line_no" | "line_type" | "description" | "amount">;

export type InvoiceTotals = { status: string; subtotal: string; tax: string; total: string };

export type IssuedInvoice = {
  invoice_id: string;
  invoice: InvoiceTotals;
  invoices: InvoiceTotals[];
  lines: InvoiceLine[];
  credit_notes: { id: string; issued_on: string; remaining_amount: string }[];
};

export type OverdueAccount = {
  tenant_id: string;
  invoice_id: string;
  total: string;
  days_overdue: number;
  tenant_status: string;
};

export type DunningAttempt = {
  invoice_id: string;
  attempt_no: number;
  scheduled_for: string;
  status: string;
};

export type DunningSchedule = {
  scheduled_for: string;
  scheduled: DunningAttempt[];
  attempts: DunningAttempt[];
};

export type SuspensionResult = {
  suspended_tenants: string[];
  subscriptions: { tenant_id: string; subscription_id: string; status: string; suspended_on: string }[];
  suspension_notifications: { id: string; tenant_id: string; kind: string; sent_at: string }[];
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BILLING_BASE_URL}${path}`, options);
  if (!response.ok) {
    throw new BillingApiError(
      `Billing service returned ${response.status}`,
      response.status,
    );
  }
  return response.json() as Promise<T>;
}

function tenantPath(tenantId: string, suffix: string) {
  return `/api/tenants/${encodeURIComponent(tenantId)}/${suffix}`;
}

function periodQuery(period: BillingPeriod) {
  return `period_start=${encodeURIComponent(period.period_start)}&period_end=${encodeURIComponent(period.period_end)}`;
}

function postJson<T>(path: string, body: unknown) {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export const billingApi = {
  listPlans: () => request<Plan[]>("/api/plans"),
  entitlement: (tenantId: string, on: string) =>
    request<Entitlement>(
      `/api/tenants/${encodeURIComponent(tenantId)}/entitlement?on=${encodeURIComponent(on)}`
    ),
  changePlan: (tenantId: string, planId: string, effectiveOn: string) =>
    request<PlanChangeResult>(
      `/api/tenants/${encodeURIComponent(tenantId)}/plan-change`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_id: planId, effective_on: effectiveOn }),
      }
    ),
  usageRating: (tenantId: string, period: BillingPeriod) =>
    request<UsageRating>(`${tenantPath(tenantId, "usage-rating")}?${periodQuery(period)}`),
  usageSummary: (tenantId: string, period: BillingPeriod) =>
    request<UsageKindSummary[]>(`${tenantPath(tenantId, "usage-summary")}?${periodQuery(period)}`),
  finalizeRating: (tenantId: string, period: BillingPeriod) =>
    postJson<FinalizedRating>(tenantPath(tenantId, "rating-periods"), period),
  invoicePreview: (tenantId: string, period: BillingPeriod) =>
    request<InvoicePreviewLine[]>(`${tenantPath(tenantId, "invoice-preview")}?${periodQuery(period)}`),
  issueInvoice: (tenantId: string, period: BillingPeriod) =>
    postJson<IssuedInvoice>(tenantPath(tenantId, "invoices"), period),
  invoiceLines: (invoiceId: string) =>
    request<InvoiceLine[]>(`/api/invoices/${encodeURIComponent(invoiceId)}/lines`),
  overdueAccounts: (asOf: string) =>
    request<OverdueAccount[]>(`/api/dunning/overdue?as_of=${encodeURIComponent(asOf)}`),
  scheduleDunning: (asOf: string) => postJson<DunningSchedule>("/api/dunning/schedule", { as_of: asOf }),
  suspendOverdue: (asOf: string) => postJson<SuspensionResult>("/api/dunning/suspend", { as_of: asOf }),
};
