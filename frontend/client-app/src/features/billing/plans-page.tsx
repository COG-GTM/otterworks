import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { billingApi, type Plan } from "./api";
import { BillingAlert } from "./alert";

const DEFAULT_TENANT = "00000000-0000-0000-0000-000000000001";

export default function BillingPlansPage() {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const requestVersion = useRef(0);

  const loadPlans = (isMounted = () => true) => {
    const submittedVersion = ++requestVersion.current;
    const isCurrent = () => submittedVersion === requestVersion.current && isMounted();
    setError("");
    setIsLoading(true);
    billingApi
      .listPlans()
      .then((items) => {
        if (isCurrent()) setPlans(items);
      })
      .catch(() => {
        if (isCurrent()) setError("Plans could not be loaded.");
      })
      .finally(() => {
        if (isCurrent()) setIsLoading(false);
      });
  };

  useEffect(() => {
    let mounted = true;
    loadPlans(() => mounted);
    return () => {
      mounted = false;
      setError("");
    };
  }, []);

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wide text-otter-600">Billing</p>
          <h1 className="text-3xl font-bold text-gray-900">Plans</h1>
        </div>
        <Link className="text-sm text-otter-700 hover:underline" to={`/billing/entitlement/${DEFAULT_TENANT}`}>
          View tenant entitlement
        </Link>
      </header>
      {error && <BillingAlert message={error} onDismiss={() => setError("")} />}
      <button
        type="button"
        onClick={() => loadPlans()}
        className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm hover:bg-gray-50"
      >
        Retry
      </button>
      {isLoading && <p role="status">Loading plans…</p>}
      {!isLoading && !error && plans.length === 0 && (
        <p className="rounded-lg bg-white p-6 text-gray-600">No plans are available.</p>
      )}
      {!isLoading && plans.length > 0 && (
        <ul className="grid gap-4 md:grid-cols-3" aria-label="Available plans">
          {plans.map((plan) => (
            <li key={plan.plan_id} className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
              <h2 className="text-xl font-semibold">{plan.code}</h2>
              <p className="mt-1 text-sm text-gray-600">{plan.tier}</p>
              <p className="mt-4 text-2xl font-bold">${plan.monthly_fee}<span className="text-sm font-normal"> / month</span></p>
              <p className="mt-2 text-sm text-gray-600">{plan.included_units} included units</p>
              <Link
                className="mt-5 inline-block rounded-lg bg-otter-600 px-3 py-2 text-sm font-semibold text-white hover:bg-otter-700"
                to={`/billing/change/${DEFAULT_TENANT}?plan=${encodeURIComponent(plan.plan_id)}`}
              >
                Choose plan
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
