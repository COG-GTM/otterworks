import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { Check, Copy, Link2 } from "lucide-react";
import { documentsApi } from "@/lib/api";
import type { ShareLink, SharePolicy } from "@/types";

const PRESET_DAYS = [1, 7, 14, 30, 90];
const DEFAULT = "default";
const NEVER = "never";

// Native (Capacitor) builds run on a device-local origin, so links must use the public web URL.
function publicWebOrigin(): string {
  return (import.meta.env.VITE_PUBLIC_WEB_URL as string | undefined)?.replace(/\/$/, "") || window.location.origin;
}

export function shareLinkUrl(link: ShareLink): string {
  return `${publicWebOrigin()}/s/${link.documentId}?token=${encodeURIComponent(link.token)}`;
}

export function formatExpiry(expiresAt: string | null): string {
  if (!expiresAt) return "Never expires";
  return `Expires ${new Date(expiresAt).toLocaleString()}`;
}

export function expiryOptions(policy: SharePolicy | undefined): number[] {
  if (!policy) return PRESET_DAYS;
  const max = policy.maxExpiryDays ?? Number.POSITIVE_INFINITY;
  const opts = PRESET_DAYS.filter((d) => d >= policy.minExpiryDays && d <= max);
  if (policy.maxExpiryDays && !opts.includes(policy.maxExpiryDays)) opts.push(policy.maxExpiryDays);
  return opts.sort((a, b) => a - b);
}

function defaultLabel(policy: SharePolicy | undefined): string {
  if (!policy) return "Workspace default";
  return policy.defaultExpiryDays
    ? `Workspace default (${policy.defaultExpiryDays} day${policy.defaultExpiryDays === 1 ? "" : "s"})`
    : "Workspace default (never expires)";
}

export function ShareLinkSection({ documentId }: { documentId: string }) {
  const [choice, setChoice] = useState<string>(DEFAULT);
  const [link, setLink] = useState<ShareLink | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [copied, setCopied] = useState(false);

  const { data: policy } = useQuery({
    queryKey: ["share-policy"],
    queryFn: () => documentsApi.getSharePolicy(),
  });

  const createLink = async () => {
    setCreating(true);
    setError(null);
    try {
      const expiry =
        choice === DEFAULT ? {} : choice === NEVER ? { noExpiry: true } : { expiresInDays: Number(choice) };
      setLink(await documentsApi.createShareLink(documentId, expiry));
    } catch (err) {
      const detail = isAxiosError(err) ? err.response?.data?.detail : null;
      setError(typeof detail === "string" ? detail : "Could not create link. Please try again.");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-2 pt-2 border-t border-gray-100" data-testid="share-link-section">
      <div className="flex items-center gap-2 text-sm font-medium text-gray-900">
        <Link2 size={14} />
        Get a read-only link
      </div>
      <div className="flex gap-2">
        <select
          aria-label="Link expiry"
          value={choice}
          onChange={(e) => setChoice(e.target.value)}
          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-otter-500"
        >
          <option value={DEFAULT}>{defaultLabel(policy)}</option>
          {expiryOptions(policy).map((d) => (
            <option key={d} value={String(d)}>
              {d} day{d === 1 ? "" : "s"}
            </option>
          ))}
          {(policy?.allowNoExpiry ?? true) && <option value={NEVER}>Never expires</option>}
        </select>
        <button
          onClick={createLink}
          disabled={creating}
          className="px-4 py-2 bg-otter-600 text-white rounded-lg text-sm hover:bg-otter-700 transition disabled:opacity-50"
        >
          {creating ? "Creating..." : "Create link"}
        </button>
      </div>
      {policy && (
        <p className="text-xs text-gray-500">
          Allowed: {policy.minExpiryDays}–{policy.maxExpiryDays ?? "∞"} days
          {policy.allowNoExpiry ? " or never" : ""}
        </p>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}
      {link && (
        <div className="flex items-center gap-2 rounded-lg bg-gray-50 p-2">
          <input
            readOnly
            value={shareLinkUrl(link)}
            aria-label="Share link URL"
            className="flex-1 bg-transparent text-xs text-gray-700 outline-none"
          />
          <span className="text-xs text-gray-500" data-testid="share-link-expiry">
            {formatExpiry(link.expiresAt)}
          </span>
          <button
            onClick={() => {
              navigator.clipboard.writeText(shareLinkUrl(link));
              setCopied(true);
              setTimeout(() => setCopied(false), 2000);
            }}
            className="flex items-center gap-1 px-2 py-1 text-xs text-gray-600 bg-white border border-gray-200 rounded hover:bg-gray-100"
          >
            {copied ? <Check size={12} /> : <Copy size={12} />}
            {copied ? "Copied!" : "Copy"}
          </button>
        </div>
      )}
    </div>
  );
}
