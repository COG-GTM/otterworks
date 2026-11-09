import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { billingApi, type DunningSchedule, type OverdueAccount, type SuspensionResult } from "./api";
import { BillingAlert } from "./alert";
import { DEFAULT_AS_OF, formatMoney } from "./format";

export default function BillingDunningPage() {
  const [draft, setDraft] = useState(DEFAULT_AS_OF);
  const [asOf, setAsOf] = useState(DEFAULT_AS_OF);
  const [accounts, setAccounts] = useState<OverdueAccount[]>([]);
  const [schedule, setSchedule] = useState<DunningSchedule | null>(null);
  const [suspension, setSuspension] = useState<SuspensionResult | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const version = useRef(0);

  useEffect(() => {
    const current = ++version.current;
    const isCurrent = () => current === version.current;
    setError("");
    setIsLoading(true);
    billingApi
      .overdueAccounts(asOf)
      .then((rows) => {
        if (isCurrent()) setAccounts(rows);
      })
      .catch(() => {
        if (isCurrent()) setError("Overdue accounts could not be loaded.");
      })
      .finally(() => {
        if (isCurrent()) setIsLoading(false);
      });
  }, [asOf, refresh]);

  useEffect(() => {
    setSchedule(null);
    setSuspension(null);
  }, [asOf]);

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

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wide text-otter-600">Billing</p>
          <h1 className="text-3xl font-bold text-gray-900">Dunning</h1>
        </div>
        <Link className="text-sm text-otter-700 hover:underline" to="/billing/plans">
          Plans
        </Link>
      </header>

      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          setAsOf(draft);
        }}
      >
        <label className="text-sm">
          As of
          <input
            type="date"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            className="mt-1 block rounded-lg border border-gray-300 px-3 py-2"
          />
        </label>
        <button type="submit" className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm">
          Load accounts
        </button>
      </form>

      {error && <BillingAlert message={error} onDismiss={() => setError("")} />}
      {isLoading && <p role="status">Loading overdue accounts…</p>}

      {!isLoading && (
        <section aria-label="Overdue accounts" className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="text-xl font-semibold">Overdue accounts</h2>
          {accounts.length === 0 ? (
            <p className="mt-2 text-sm text-gray-500">No overdue accounts.</p>
          ) : (
            <table className="mt-4 w-full text-left text-sm">
              <thead>
                <tr className="text-gray-500">
                  <th>Tenant</th><th>Invoice</th><th className="pr-6 text-right">Total</th><th>Days overdue</th><th>Status</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((row) => (
                  <tr key={row.invoice_id}>
                    <td>
                      <Link className="text-otter-700 hover:underline" to={`/billing/invoices/${row.tenant_id}`}>
                        {row.tenant_id}
                      </Link>
                    </td>
                    <td>{row.invoice_id}</td>
                    <td className="pr-6 text-right">{formatMoney(row.total)}</td>
                    <td>{row.days_overdue}</td>
                    <td>{row.tenant_status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="mt-4 flex gap-3">
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() =>
                run(async () => setSchedule(await billingApi.scheduleDunning(asOf)), "Dunning could not be scheduled.")
              }
              className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm disabled:opacity-50"
            >
              Schedule dunning
            </button>
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() =>
                run(async () => setSuspension(await billingApi.suspendOverdue(asOf)), "Overdue accounts could not be suspended.")
              }
              className="rounded-lg bg-red-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              Suspend overdue accounts
            </button>
          </div>
        </section>
      )}

      {schedule && (
        <section aria-label="Dunning schedule" className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="text-xl font-semibold">Scheduled for {schedule.scheduled_for}</h2>
          <ul className="mt-2 text-sm">
            {schedule.scheduled.map((item) => (
              <li key={`${item.invoice_id}-${item.attempt_no}`}>
                Invoice {item.invoice_id}: attempt {item.attempt_no} {item.status}
              </li>
            ))}
          </ul>
        </section>
      )}

      {suspension && (
        <section aria-label="Suspension result" className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="text-xl font-semibold">Suspension</h2>
          {suspension.suspended_tenants.length === 0 ? (
            <p className="mt-2 text-sm">No active tenants needed suspension.</p>
          ) : (
            <ul className="mt-2 text-sm">
              {suspension.suspended_tenants.map((tenant) => (
                <li key={tenant}>Tenant {tenant} suspended</li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-sm text-gray-600">
            Suspension notifications on record: {suspension.suspension_notifications.length}
          </p>
        </section>
      )}
    </main>
  );
}
