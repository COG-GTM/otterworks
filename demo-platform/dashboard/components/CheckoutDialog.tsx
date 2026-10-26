"use client";

import { useEffect, useState } from "react";
import { apiSend } from "@/lib/client";
import type { Tenant, TenantTier } from "@/lib/types";

export default function CheckoutDialog({
  open,
  onClose,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const [id, setId] = useState("");
  const [owner, setOwner] = useState("");
  const [branch, setBranch] = useState("");
  const [tier, setTier] = useState<TenantTier>("A");
  const [ttl, setTtl] = useState("8h");
  const [imageTag, setImageTag] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setId("");
      setOwner("");
      setBranch("");
      setTier("A");
      setTtl("8h");
      setImageTag("");
      setError(null);
    }
  }, [open]);

  if (!open) return null;

  const effectiveBranch = branch.trim() || (id.trim() ? `workshop-${id.trim()}` : "workshop-<id>");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiSend<Tenant>("/api/tenants/checkout", "POST", {
        id: id.trim() || undefined,
        owner: owner.trim() || undefined,
        branch: branch.trim() || undefined,
        tier,
        ttl,
        image_tag: imageTag.trim() || undefined,
      });
      onDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "checkout failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <form
        onSubmit={submit}
        className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-lg"
      >
        <h2 className="text-lg font-semibold">Checkout tenant</h2>

        <div className="mt-4 grid grid-cols-2 gap-4">
          <Field label="Tenant id (optional)">
            <input
              value={id}
              onChange={(e) => setId(e.target.value)}
              placeholder="auto"
              className="input"
            />
          </Field>
          <Field label="Owner">
            <input
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
              placeholder="facilitator"
              className="input"
            />
          </Field>
          <Field label="Branch" className="col-span-2">
            <input
              value={branch}
              onChange={(e) => setBranch(e.target.value)}
              placeholder={effectiveBranch}
              className="input"
            />
          </Field>
          <Field label="Tier">
            <select
              value={tier}
              onChange={(e) => setTier(e.target.value === "B" ? "B" : "A")}
              className="input"
            >
              <option value="A">A (logical)</option>
              <option value="B">B (physical)</option>
            </select>
          </Field>
          <Field label="TTL">
            <input value={ttl} onChange={(e) => setTtl(e.target.value)} className="input" />
          </Field>
          <Field label="Image tag (optional)" className="col-span-2">
            <input
              value={imageTag}
              onChange={(e) => setImageTag(e.target.value)}
              placeholder="golden"
              pattern="\s*[A-Za-z0-9_][A-Za-z0-9_.\-]{0,127}\s*"
              title="Docker tag: letters, digits, _ . - (max 128, not starting with . or -)"
              className="input"
            />
          </Field>
        </div>

        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

        <div className="mt-6 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button type="submit" disabled={busy} className="btn-primary">
            {busy ? "Checking out…" : "Checkout"}
          </button>
        </div>
      </form>
    </div>
  );
}

function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={`block text-sm ${className ?? ""}`}>
      <span className="font-medium text-slate-700">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}
