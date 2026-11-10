import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { format } from "date-fns";
import { AlertCircle, Check, Clock, Copy, Link2 } from "lucide-react";
import { shareLinksApi } from "@/lib/api";
import type { DocumentShareLink, SharePolicy } from "@/types";

export function shareLinkUrl(link: Pick<DocumentShareLink, "documentId" | "token">): string {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  return `${origin}/share/${link.documentId}?token=${encodeURIComponent(link.token)}`;
}

export function formatExpiry(iso: string): string {
  return format(new Date(iso), "MMM d, yyyy h:mm a");
}

export function isLinkExpired(link: DocumentShareLink, now = new Date()): boolean {
  return link.expired ?? new Date(link.expiresAt).getTime() <= now.getTime();
}

function daysLabel(days: number): string {
  return `${days} ${days === 1 ? "day" : "days"}`;
}

export function shareLinkErrorMessage(err: unknown, fallback: string): string {
  if (isAxiosError(err)) {
    const status = err.response?.status;
    const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string" && detail) return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const msg = (detail[0] as { msg?: unknown })?.msg;
      if (typeof msg === "string") return msg;
    }
    if (status === 410) return "This share link has expired";
    if (status === 403) return "Only the document owner can manage share links";
  }
  return fallback;
}

function ExpirySelect({
  policy,
  value,
  onChange,
  label,
  disabled,
}: Readonly<{
  policy: SharePolicy;
  value: number;
  onChange: (days: number) => void;
  label: string;
  disabled?: boolean;
}>) {
  const options: number[] = [];
  for (let d = policy.minExpiryDays; d <= policy.maxExpiryDays; d++) options.push(d);
  return (
    <select
      aria-label={label}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(Number(e.target.value))}
      className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-otter-500 disabled:opacity-50"
    >
      {options.map((d) => (
        <option key={d} value={d}>
          {daysLabel(d)}
          {d === policy.defaultExpiryDays ? " (workspace default)" : ""}
        </option>
      ))}
    </select>
  );
}

function CopyButton({ text }: Readonly<{ text: string }>) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
        } catch {
          return;
        }
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
      className="flex items-center gap-1.5 px-2.5 py-1.5 bg-white border border-gray-300 rounded-lg text-xs font-medium text-gray-700 hover:bg-gray-50 transition flex-shrink-0"
    >
      {copied ? <Check size={12} className="text-green-500" /> : <Copy size={12} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function ShareLinkRow({
  link,
  policy,
}: Readonly<{ link: DocumentShareLink; policy: SharePolicy }>) {
  const queryClient = useQueryClient();
  const expired = isLinkExpired(link);
  const [days, setDays] = useState(policy.defaultExpiryDays);
  const [error, setError] = useState<string | null>(null);

  const update = useMutation({
    mutationFn: () => shareLinksApi.updateExpiry(link.documentId, link.id, days),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["share-links", link.documentId] });
    },
    onError: (err) => {
      setError(shareLinkErrorMessage(err, "Could not change the link expiry. Please try again."));
      if (isAxiosError(err) && err.response?.status === 410) {
        queryClient.invalidateQueries({ queryKey: ["share-links", link.documentId] });
      }
    },
  });

  return (
    <li className="py-3 space-y-2" data-testid={`share-link-${link.id}`}>
      <div className="flex items-center gap-2">
        <Link2 size={16} className="text-gray-400 flex-shrink-0" />
        <p className="flex-1 min-w-0 text-sm text-gray-700 truncate">{shareLinkUrl(link)}</p>
        {!expired && <CopyButton text={shareLinkUrl(link)} />}
      </div>
      <div className="flex items-center gap-2 flex-wrap pl-6">
        {expired ? (
          <span className="text-xs font-medium text-red-700 bg-red-50 px-2 py-0.5 rounded-full">
            Expired {formatExpiry(link.expiresAt)}
          </span>
        ) : (
          <>
            <span className="flex items-center gap-1 text-xs text-gray-500">
              <Clock size={12} />
              Expires {formatExpiry(link.expiresAt)}
            </span>
            <span className="text-xs text-gray-400">·</span>
            <ExpirySelect
              policy={policy}
              value={days}
              onChange={setDays}
              label={`New expiry for link ${link.id}`}
              disabled={update.isPending}
            />
            <button
              type="button"
              onClick={() => update.mutate()}
              disabled={update.isPending}
              className="px-3 py-1.5 text-xs font-medium text-otter-700 border border-otter-200 rounded-lg hover:bg-otter-50 disabled:opacity-50"
            >
              {update.isPending ? "Saving..." : "Change expiry"}
            </button>
          </>
        )}
      </div>
      {error && (
        <p role="alert" className="pl-6 text-xs text-red-600">
          {error}
        </p>
      )}
    </li>
  );
}

export function ShareLinkPanel({ documentId }: Readonly<{ documentId: string }>) {
  const queryClient = useQueryClient();
  const [days, setDays] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<DocumentShareLink | null>(null);

  const policyQuery = useQuery({
    queryKey: ["share-policy"],
    queryFn: () => shareLinksApi.getPolicy(),
  });
  const linksQuery = useQuery({
    queryKey: ["share-links", documentId],
    queryFn: () => shareLinksApi.list(documentId),
  });

  const create = useMutation({
    mutationFn: (expiresInDays?: number) => shareLinksApi.create(documentId, expiresInDays),
    onMutate: () => setCreated(null),
    onSuccess: (link) => {
      setError(null);
      setCreated(link);
      queryClient.invalidateQueries({ queryKey: ["share-links", documentId] });
    },
    onError: (err) => {
      setError(shareLinkErrorMessage(err, "Could not create a share link. Please try again."));
    },
  });

  const policy = policyQuery.data;

  if (policyQuery.isLoading) {
    return <p className="text-sm text-gray-500">Loading link settings...</p>;
  }
  if (!policy) {
    return (
      <p role="alert" className="text-sm text-red-600">
        Share link settings could not be loaded.
      </p>
    );
  }

  const selected = days ?? policy.defaultExpiryDays;
  const links = linksQuery.data ?? [];

  return (
    <div className="space-y-4" aria-label="Share link">
      <div className="space-y-2">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Get link</p>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm text-gray-700">Expires after</span>
          <ExpirySelect
            policy={policy}
            value={selected}
            onChange={setDays}
            label="Link expiry"
            disabled={create.isPending}
          />
          <button
            type="button"
            onClick={() => create.mutate(days ?? undefined)}
            disabled={create.isPending}
            className="px-4 py-2 bg-otter-600 text-white rounded-lg text-sm font-medium hover:bg-otter-700 transition disabled:opacity-50"
          >
            {create.isPending ? "Creating..." : "Create link"}
          </button>
        </div>
        <p className="text-xs text-gray-500">
          Workspace default: {daysLabel(policy.defaultExpiryDays)}. Allowed range:{" "}
          {policy.minExpiryDays} to {policy.maxExpiryDays} days.
        </p>
        {error && (
          <div
            role="alert"
            className="flex items-start gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700"
          >
            <AlertCircle size={16} className="mt-0.5 flex-shrink-0 text-red-500" />
            <span>{error}</span>
          </div>
        )}
        {created && (
          <div
            data-testid="created-share-link"
            className="flex items-center gap-3 p-3 bg-green-50 border border-green-200 rounded-xl"
          >
            <Link2 size={18} className="text-green-600 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm text-gray-800 truncate">{shareLinkUrl(created)}</p>
              <p className="text-xs text-gray-600">Expires {formatExpiry(created.expiresAt)}</p>
            </div>
            <CopyButton text={shareLinkUrl(created)} />
          </div>
        )}
      </div>

      <div>
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">
          Existing links
        </p>
        {linksQuery.isLoading ? (
          <p className="text-sm text-gray-500 py-2">Loading links...</p>
        ) : links.length === 0 ? (
          <p className="text-sm text-gray-500 py-2">No share links yet</p>
        ) : (
          <ul aria-label="Existing share links" className="divide-y divide-gray-100">
            {links.map((link) => (
              <ShareLinkRow key={link.id} link={link} policy={policy} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
