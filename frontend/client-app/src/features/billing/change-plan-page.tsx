import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { billingApi, type Plan, type PlanChangeResult } from "./api";
import { BillingAlert } from "./alert";

const UUID = /^[0-9a-f-]{36}$/i;

export default function BillingChangePlanPage() {
  const { tenantId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [plans, setPlans] = useState<Plan[]>([]);
  const [planId, setPlanId] = useState(searchParams.get("plan") ?? "");
  const [effectiveOn, setEffectiveOn] = useState("2026-03-01");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<PlanChangeResult | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let mounted = true;
    if (!tenantId || !UUID.test(tenantId)) {
      setError("A valid tenant id is required.");
      setIsLoading(false);
      return () => {
        mounted = false;
        setError("");
      };
    }
    billingApi
      .listPlans()
      .then((items) => {
        if (mounted) {
          setPlans(items);
          setPlanId((current) => current || items[0]?.plan_id || "");
        }
      })
      .catch(() => {
        if (mounted) setError("Plans could not be loaded.");
      })
      .finally(() => {
        if (mounted) setIsLoading(false);
      })
      .catch(() => undefined);
    return () => {
      mounted = false;
      setError("");
    };
  }, [tenantId, retry]);

  const submit = () => {
    if (!tenantId || !UUID.test(tenantId) || !planId || !effectiveOn) {
      setError("Choose a plan and effective date.");
      return;
    }
    setError("");
    setIsSaving(true);
    billingApi
      .changePlan(tenantId, planId, effectiveOn)
      .then(setResult)
      .catch(() => setError("The plan change could not be saved."))
      .finally(() => setIsSaving(false))
      .catch(() => undefined);
  };

  return (
    <main className="mx-auto max-w-2xl space-y-6 p-6">
      <button
        type="button"
        onClick={() => (window.history.length > 1 ? navigate(-1) : navigate("/billing/plans"))}
        className="text-sm text-otter-700 hover:underline"
      >
        Back
      </button>
      <h1 className="text-3xl font-bold">Change plan</h1>
      {error && <BillingAlert message={error} onDismiss={() => setError("")} />}
      {error && (
        <button
          type="button"
          onClick={() => {
            setError("");
            setIsLoading(true);
            setRetry((value) => value + 1);
          }}
          className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm"
        >
          Retry
        </button>
      )}
      {isLoading && <p role="status">Loading plans…</p>}
      {!isLoading && plans.length === 0 && <p>No plans are available.</p>}
      {!isLoading && plans.length > 0 && (
        <form
          className="space-y-5 rounded-xl border border-gray-200 bg-white p-6 shadow-sm"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <div>
            <label htmlFor="billing-plan" className="mb-1 block text-sm font-medium">Plan</label>
            <select id="billing-plan" value={planId} onChange={(event) => setPlanId(event.target.value)} className="w-full rounded-lg border border-gray-300 px-3 py-2">
              {plans.map((plan) => <option key={plan.plan_id} value={plan.plan_id}>{plan.code}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="effective-on" className="mb-1 block text-sm font-medium">Effective date</label>
            <input
              id="effective-on"
              type="date"
              value={effectiveOn}
              onChange={(event) => setEffectiveOn(event.target.value)}
              aria-describedby={error ? "billing-change-error" : undefined}
              className="w-full rounded-lg border border-gray-300 px-3 py-2"
            />
            {error && <span id="billing-change-error" className="sr-only">{error}</span>}
          </div>
          <button type="submit" disabled={isSaving} className="rounded-lg bg-otter-600 px-4 py-2 font-semibold text-white disabled:opacity-50">
            {isSaving ? "Saving…" : "Save plan change"}
          </button>
        </form>
      )}
      {result && <p role="status" className="rounded-lg bg-green-50 p-4 text-green-800">Plan change saved for {result.latest_start}.</p>}
    </main>
  );
}
