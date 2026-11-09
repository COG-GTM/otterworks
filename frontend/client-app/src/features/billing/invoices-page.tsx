import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  billingApi,
  BillingApiError,
  type BillingPeriod,
  type FinalizedRating,
  type InvoiceLine,
  type InvoicePreviewLine,
  type IssuedInvoice,
  type UsageKindSummary,
  type UsageRating,
} from "./api";
import { BillingAlert } from "./alert";
import { DEFAULT_PERIOD, formatMoney } from "./format";

const UUID = /^[0-9a-f-]{36}$/i;

type PeriodData = {
  rating: UsageRating;
  summary: UsageKindSummary[];
  preview: InvoicePreviewLine[];
};

export default function BillingInvoicesPage() {
  const { tenantId = "" } = useParams();
  const [draft, setDraft] = useState<BillingPeriod>(DEFAULT_PERIOD);
  const [period, setPeriod] = useState<BillingPeriod>(DEFAULT_PERIOD);
  const [data, setData] = useState<PeriodData | null>(null);
  const [finalized, setFinalized] = useState<FinalizedRating | null>(null);
  const [issued, setIssued] = useState<IssuedInvoice | null>(null);
  const [lines, setLines] = useState<InvoiceLine[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const version = useRef(0);

  useEffect(() => {
    const current = ++version.current;
    const isCurrent = () => current === version.current;
    setData(null);
    setError("");
    if (!UUID.test(tenantId)) {
      setError("A valid tenant id is required.");
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    Promise.all([
      billingApi.usageRating(tenantId, period),
      billingApi.usageSummary(tenantId, period),
      billingApi.invoicePreview(tenantId, period),
    ])
      .then(([rating, summary, preview]) => {
        if (isCurrent()) setData({ rating, summary, preview });
      })
      .catch((reason: unknown) => {
        if (!isCurrent()) return;
        setError(
          reason instanceof BillingApiError && reason.status === 404
            ? "No subscription covers this period."
            : "Billing data could not be loaded.",
        );
      })
      .finally(() => {
        if (isCurrent()) setIsLoading(false);
      });
  }, [tenantId, period, refresh]);

  useEffect(() => {
    setFinalized(null);
    setIssued(null);
    setLines([]);
  }, [tenantId, period]);

  const run = async (action: () => Promise<void>, failure: string) => {
    setIsSubmitting(true);
    setError("");
    try {
      await action();
      setRefresh((value) => value + 1);
    } catch {
      setError(failure);
    } finally {
      setIsSubmitting(false);
    }
  };

  const finalize = () =>
    run(async () => {
      setFinalized(await billingApi.finalizeRating(tenantId, period));
    }, "The rating period could not be finalized.");

  const issue = () =>
    run(async () => {
      const invoice = await billingApi.issueInvoice(tenantId, period);
      setIssued(invoice);
      setLines(await billingApi.invoiceLines(invoice.invoice_id));
    }, "The invoice could not be issued.");

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wide text-otter-600">Billing</p>
          <h1 className="text-3xl font-bold text-gray-900">Usage and invoices</h1>
          <p className="text-sm text-gray-600">Tenant {tenantId}</p>
        </div>
        <nav className="flex gap-4 text-sm">
          <Link className="text-otter-700 hover:underline" to={`/billing/entitlement/${tenantId}`}>
            Entitlement
          </Link>
          <Link className="text-otter-700 hover:underline" to="/billing/dunning">
            Dunning
          </Link>
        </nav>
      </header>

      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          setPeriod({ ...draft });
        }}
      >
        <label className="text-sm">
          Period start
          <input
            type="date"
            value={draft.period_start}
            onChange={(event) => setDraft({ ...draft, period_start: event.target.value })}
            className="mt-1 block rounded-lg border border-gray-300 px-3 py-2"
          />
        </label>
        <label className="text-sm">
          Period end
          <input
            type="date"
            value={draft.period_end}
            onChange={(event) => setDraft({ ...draft, period_end: event.target.value })}
            className="mt-1 block rounded-lg border border-gray-300 px-3 py-2"
          />
        </label>
        <button type="submit" className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm">
          Load period
        </button>
      </form>

      {error && <BillingAlert message={error} onDismiss={() => setError("")} />}
      {isLoading && <p role="status">Loading billing period…</p>}

      {!isLoading && data && (
        <>
          <section aria-label="Usage rating" className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <h2 className="text-xl font-semibold">Usage rating</h2>
            <dl className="mt-4 grid gap-3 sm:grid-cols-4">
              <Stat label="Used units" value={data.rating.used_units} />
              <Stat label="Included units" value={data.rating.quota_units} />
              <Stat label="Rollover units" value={data.rating.rollover_units} />
              <Stat label="Billable units" value={data.rating.billable_units} />
              <Stat label="First tier units" value={data.rating.first_tier_units} />
              <Stat label="Second tier units" value={data.rating.second_tier_units} />
              <Stat label="Overage" value={formatMoney(data.rating.overage_amount)} />
            </dl>
            <table className="mt-4 w-full text-left text-sm">
              <caption className="sr-only">Usage by kind</caption>
              <thead>
                <tr className="text-gray-500"><th>Kind</th><th>Events</th><th>Units</th></tr>
              </thead>
              <tbody>
                {data.summary.map((row) => (
                  <tr key={row.kind}><td>{row.kind}</td><td>{row.event_count}</td><td>{row.units}</td></tr>
                ))}
              </tbody>
            </table>
            {data.summary.length === 0 && <p className="mt-2 text-sm text-gray-500">No usage in this period.</p>}
            <button
              type="button"
              disabled={isSubmitting}
              onClick={finalize}
              className="mt-4 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm disabled:opacity-50"
            >
              Finalize rating
            </button>
            {finalized && (
              <p role="status" className="mt-2 text-sm text-gray-700">
                Rating finalized: {finalized.result.billable_units} billable units,
                rollover {finalized.result.rollover_units}, overage {formatMoney(finalized.result.overage_amount)}.
              </p>
            )}
          </section>

          <section aria-label="Invoice preview" className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <h2 className="text-xl font-semibold">Invoice preview</h2>
            <LineTable lines={data.preview.map((line) => ({ ...line, amount: line.total }))} label="Preview lines" />
            <button
              type="button"
              disabled={isSubmitting}
              onClick={issue}
              className="mt-4 rounded-lg bg-otter-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              Issue invoice
            </button>
          </section>
        </>
      )}

      {issued && (
        <section aria-label="Issued invoice" className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="text-xl font-semibold">Issued invoice</h2>
          <p className="text-sm text-gray-600">Invoice {issued.invoice_id}</p>
          <dl className="mt-4 grid gap-3 sm:grid-cols-4">
            <Stat label="Status" value={issued.invoice.status} />
            <Stat label="Subtotal" value={formatMoney(issued.invoice.subtotal)} />
            <Stat label="Tax" value={formatMoney(issued.invoice.tax)} />
            <Stat label="Total" value={formatMoney(issued.invoice.total)} />
          </dl>
          <LineTable lines={lines} label="Invoice lines" />
          {issued.credit_notes.length > 0 && (
            <ul className="mt-4 text-sm text-gray-700">
              {issued.credit_notes.map((note) => (
                <li key={note.id}>
                  Credit note issued {note.issued_on}: {formatMoney(note.remaining_amount)} remaining
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </main>
  );
}

function Stat({ label, value }: Readonly<{ label: string; value: string | number }>) {
  return (
    <div>
      <dt className="text-sm text-gray-500">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function LineTable({ lines, label }: Readonly<{ lines: InvoiceLine[]; label: string }>) {
  return (
    <table className="mt-4 w-full text-left text-sm">
      <caption className="sr-only">{label}</caption>
      <thead>
        <tr className="text-gray-500"><th>#</th><th>Type</th><th>Description</th><th className="text-right">Amount</th></tr>
      </thead>
      <tbody>
        {lines.map((line) => (
          <tr key={line.line_no}>
            <td>{line.line_no}</td>
            <td>{line.line_type}</td>
            <td>{line.description}</td>
            <td className="text-right">{formatMoney(line.amount)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
