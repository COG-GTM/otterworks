import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { format } from "date-fns";
import { AlertCircle, Check, Copy, Link2, Lock } from "lucide-react";
import toast from "react-hot-toast";
import { shareLinksApi } from "@/lib/api";
import type { ShareLink } from "@/types";

const PRESET_DAYS = [1, 7, 14, 30, 60, 90];

export function expiryDayOptions(defaultDays: number, maxDays: number): number[] {
  return Array.from(new Set([...PRESET_DAYS, defaultDays, maxDays]))
    .filter((d) => d >= 1 && d <= maxDays)
    .sort((a, b) => a - b);
}

// Prefer the server's absolute URL: in native/desktop builds window.location.origin is a
// WebView or loopback address that recipients on other devices cannot open.
export function shareLinkUrl(link: Pick<ShareLink, "token" | "url">): string {
  if (link.url && /^https?:\/\//i.test(link.url)) return link.url;
  return `${window.location.origin}/s/${link.token}`;
}

export function formatExpiry(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : format(date, "PPP");
}

function isActive(link: ShareLink): boolean {
  return !link.expiredAt && new Date(link.expiresAt).getTime() > Date.now();
}

function daysLabel(days: number): string {
  return days === 1 ? "1 day" : `${days} days`;
}

function errorMessage(err: unknown, fallback: string): string {
  if (isAxiosError(err)) {
    const status = err.response?.status;
    const data = err.response?.data as
      | { detail?: unknown; message?: string; error?: string }
      | undefined;
    if (status === 403) return "Only the folder owner can manage its share link.";
    if (typeof data?.detail === "string") return data.detail;
    if (data?.message) return data.message;
    if (status === 422) return "That expiry is outside the workspace limits.";
  }
  return fallback;
}

interface FolderShareLinkPanelProps {
  folderId: string;
}

export function FolderShareLinkPanel({ folderId }: FolderShareLinkPanelProps) {
  const queryClient = useQueryClient();
  const policyQuery = useQuery({
    queryKey: ["share-policy"],
    queryFn: shareLinksApi.getPolicy,
    retry: false,
  });
  const linksQuery = useQuery({
    queryKey: ["share-links", folderId],
    queryFn: () => shareLinksApi.listForResource(folderId),
    retry: false,
  });

  const [link, setLink] = useState<ShareLink | null>(null);
  const [days, setDays] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const policy = policyQuery.data;
  const options = useMemo(
    () => (policy ? expiryDayOptions(policy.defaultDays, policy.maxDays) : []),
    [policy]
  );

  useEffect(() => {
    if (link || !linksQuery.data) return;
    const existing = linksQuery.data.find(isActive);
    if (existing) setLink(existing);
  }, [link, linksQuery.data]);

  useEffect(() => {
    if (policy && days === null) {
      setDays(Math.min(policy.defaultDays, policy.maxDays));
    }
  }, [policy, days]);

  const handleCreate = async () => {
    if (days === null) return;
    setBusy(true);
    setError(null);
    try {
      const created = await shareLinksApi.createFolderLink(folderId, days);
      setLink(created);
      queryClient.invalidateQueries({ queryKey: ["share-links", folderId] });
      toast.success("Link created");
    } catch (err) {
      setError(errorMessage(err, "Could not create the link."));
    } finally {
      setBusy(false);
    }
  };

  const handleUpdate = async () => {
    if (!link || days === null) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await shareLinksApi.updateExpiry(link.id, days);
      setLink(updated);
      queryClient.invalidateQueries({ queryKey: ["share-links", folderId] });
      toast.success("Expiry updated");
    } catch (err) {
      setError(errorMessage(err, "Could not update the expiry."));
    } finally {
      setBusy(false);
    }
  };

  const handleCopy = async () => {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(shareLinkUrl(link));
      setCopied(true);
      toast.success("Link copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Failed to copy link");
    }
  };

  if (policyQuery.isLoading || linksQuery.isLoading) {
    return <p className="text-sm text-gray-500 py-4 text-center">Loading link settings…</p>;
  }

  if (policyQuery.isError || !policy) {
    return (
      <div
        role="alert"
        className="flex items-start gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700"
      >
        <AlertCircle size={16} className="mt-0.5 flex-shrink-0 text-red-500" />
        <span className="flex-1">Could not load the workspace link policy.</span>
        <button onClick={() => policyQuery.refetch()} className="font-medium underline">
          Retry
        </button>
      </div>
    );
  }

  const picker = (label: string) => (
    <div className="space-y-1.5">
      <label htmlFor="share-link-expiry" className="text-xs font-medium text-gray-500 uppercase tracking-wider">
        {label}
      </label>
      <select
        id="share-link-expiry"
        value={days ?? ""}
        onChange={(e) => setDays(Number(e.target.value))}
        disabled={busy}
        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-otter-500"
      >
        {options.map((d) => (
          <option key={d} value={d}>
            {daysLabel(d)}
            {d === policy.defaultDays ? " (workspace default)" : ""}
          </option>
        ))}
      </select>
      <p className="text-xs text-gray-500">
        Links can last up to {daysLabel(policy.maxDays)} in this workspace.
      </p>
    </div>
  );

  return (
    <div className="space-y-4">
      {error && (
        <div
          role="alert"
          className="flex items-start gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700"
        >
          <AlertCircle size={16} className="mt-0.5 flex-shrink-0 text-red-500" />
          <span className="break-words min-w-0">{error}</span>
        </div>
      )}

      <div className="flex items-start gap-2 text-xs text-gray-500">
        <Lock size={14} className="mt-0.5 flex-shrink-0" />
        <span>Anyone with the link can view this folder&rsquo;s files (read-only) until the link expires.</span>
      </div>

      {link ? (
        <>
          <div className="flex items-center gap-3 p-4 bg-gray-50 rounded-xl">
            <Link2 size={20} className="text-gray-400 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <input
                readOnly
                aria-label="Share link URL"
                value={shareLinkUrl(link)}
                className="w-full bg-transparent text-sm text-gray-700 truncate focus:outline-none"
                onFocus={(e) => e.target.select()}
              />
              <p className="text-xs text-gray-500 mt-0.5" data-testid="share-link-expiry">
                Expires on {formatExpiry(link.expiresAt)}
              </p>
            </div>
            <button
              onClick={handleCopy}
              className="flex items-center gap-1.5 px-3 py-2 bg-white border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 transition flex-shrink-0"
            >
              {copied ? (
                <>
                  <Check size={14} className="text-green-500" />
                  Copied
                </>
              ) : (
                <>
                  <Copy size={14} />
                  Copy link
                </>
              )}
            </button>
          </div>
          {picker("Change expiry")}
          <button
            onClick={handleUpdate}
            disabled={busy || days === null}
            className="w-full px-4 py-2.5 bg-white border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {busy ? "Saving…" : "Update expiry"}
          </button>
        </>
      ) : (
        <>
          {picker("Link expires in")}
          <button
            onClick={handleCreate}
            disabled={busy || days === null}
            className="w-full px-4 py-2.5 bg-otter-600 text-white rounded-lg text-sm font-medium hover:bg-otter-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {busy ? "Creating…" : "Create link"}
          </button>
        </>
      )}
    </div>
  );
}
