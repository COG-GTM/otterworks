import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import toast from "react-hot-toast";
import { X, Link2, Copy, Check, AlertCircle, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  DEFAULT_SHARING_POLICY,
  folderShareLinksApi,
  folderShareUrl,
  sharingPolicyApi,
} from "@/lib/api";
import type { CreatedFolderShareLink, FolderShareLink, FolderShareLinkStatus } from "@/types";

interface FolderShareDialogProps {
  folderId: string;
  folderName: string;
  onClose: () => void;
}

const STATUS_STYLES: Record<FolderShareLinkStatus, { label: string; className: string }> = {
  active: { label: "Active", className: "bg-green-50 text-green-700" },
  expired: { label: "Expired", className: "bg-gray-100 text-gray-600" },
  revoked: { label: "Revoked", className: "bg-red-50 text-red-700" },
};

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function rangeMessage(min: number, max: number): string {
  return `Choose an expiry between ${min} and ${max} days.`;
}

function errorMessage(err: unknown, fallback: string, min: number, max: number): string {
  if (isAxiosError(err)) {
    const status = err.response?.status;
    if (status === 403) return "Only the folder owner can manage share links.";
    if (status === 422) return rangeMessage(min, max);
    if (status === 409) return "This link has already expired or been revoked.";
  }
  return fallback;
}

export function FolderShareDialog({ folderId, folderName, onClose }: FolderShareDialogProps) {
  const queryClient = useQueryClient();
  const linksKey = ["folder-share-links", folderId];

  const { data: policy = DEFAULT_SHARING_POLICY, isLoading: policyLoading } = useQuery({
    queryKey: ["sharing-policy"],
    queryFn: sharingPolicyApi.get,
    staleTime: 60_000,
  });
  const { minExpiryDays: min, maxExpiryDays: max, defaultExpiryDays } = policy;

  const {
    data: links = [],
    isLoading: linksLoading,
    isError: linksError,
  } = useQuery({
    queryKey: linksKey,
    queryFn: () => folderShareLinksApi.list(folderId),
  });

  const [expiryInput, setExpiryInput] = useState(String(defaultExpiryDays));
  const [expiryTouched, setExpiryTouched] = useState(false);
  const [created, setCreated] = useState<CreatedFolderShareLink | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!expiryTouched) setExpiryInput(String(defaultExpiryDays));
  }, [defaultExpiryDays, expiryTouched]);

  const expiryDays = Number(expiryInput);
  const expiryValid =
    expiryInput.trim() !== "" && Number.isInteger(expiryDays) && expiryDays >= min && expiryDays <= max;

  const createMutation = useMutation({
    mutationFn: () =>
      folderShareLinksApi.create(
        folderId,
        expiryDays === defaultExpiryDays && !expiryTouched ? undefined : expiryDays
      ),
    onSuccess: (link) => {
      setError(null);
      setCreated(link);
      setCopied(false);
      queryClient.invalidateQueries({ queryKey: linksKey });
      toast.success("Share link created");
    },
    onError: (err) => {
      const message = errorMessage(err, "Could not create the share link.", min, max);
      setError(message);
      toast.error(message);
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => folderShareLinksApi.revoke(id),
    onSuccess: (_data, id) => {
      setError(null);
      if (created?.id === id) setCreated(null);
      queryClient.invalidateQueries({ queryKey: linksKey });
      toast.success("Link revoked");
    },
    onError: (err) => {
      const message = errorMessage(err, "Could not revoke the link.", min, max);
      setError(message);
      toast.error(message);
    },
  });

  const handleCopy = async () => {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(folderShareUrl(created.token));
      setCopied(true);
      toast.success("Link copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Failed to copy link");
    }
  };

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="folder-share-dialog-title"
          className="bg-white rounded-2xl shadow-2xl w-full max-w-lg"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
            <h2 id="folder-share-dialog-title" className="text-lg font-semibold text-gray-900">
              Share link for &ldquo;{folderName}&rdquo;
            </h2>
            <button
              onClick={onClose}
              aria-label="Close"
              className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition"
            >
              <X size={18} />
            </button>
          </div>

          <div className="px-6 py-5 space-y-5">
            {error && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
              >
                <AlertCircle size={16} className="mt-0.5 flex-shrink-0 text-red-500" />
                <span className="break-words min-w-0">{error}</span>
              </div>
            )}

            {/* Create link */}
            <div className="space-y-3">
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">
                New link
              </p>
              <p className="text-xs text-gray-500">
                Anyone with the link can view this folder&rsquo;s files until it expires.
              </p>
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <label htmlFor="folder-share-expiry" className="block text-sm font-medium text-gray-700 mb-1">
                    Expires after (days)
                  </label>
                  <input
                    id="folder-share-expiry"
                    type="number"
                    inputMode="numeric"
                    min={min}
                    max={max}
                    step={1}
                    required
                    value={expiryInput}
                    disabled={policyLoading}
                    onChange={(e) => {
                      setExpiryTouched(true);
                      setExpiryInput(e.target.value);
                    }}
                    aria-invalid={!expiryValid}
                    aria-describedby="folder-share-expiry-help"
                    className={cn(
                      "w-full px-3.5 py-2.5 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-otter-500 focus:border-transparent transition",
                      expiryValid ? "border-gray-300" : "border-red-300"
                    )}
                  />
                </div>
                <button
                  onClick={() => createMutation.mutate()}
                  disabled={!expiryValid || policyLoading || createMutation.isPending}
                  className="flex items-center gap-2 px-4 py-2.5 bg-otter-600 text-white rounded-lg text-sm font-medium hover:bg-otter-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Link2 size={16} />
                  {createMutation.isPending ? "Creating..." : "Create link"}
                </button>
              </div>
              <p
                id="folder-share-expiry-help"
                className={cn("text-xs", expiryValid ? "text-gray-500" : "text-red-600")}
              >
                {expiryValid
                  ? `Workspace default: ${defaultExpiryDays} days. Allowed: ${min} to ${max} days.`
                  : rangeMessage(min, max)}
              </p>
            </div>

            {created && (
              <div className="space-y-2 rounded-xl border border-otter-300 bg-otter-50 p-3">
                <div className="flex gap-2">
                  <input
                    type="text"
                    readOnly
                    aria-label="Share link URL"
                    value={folderShareUrl(created.token)}
                    className="flex-1 min-w-0 px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm bg-white text-gray-600 truncate"
                  />
                  <button
                    onClick={handleCopy}
                    className={cn(
                      "flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition whitespace-nowrap",
                      copied
                        ? "bg-green-50 text-green-700 border border-green-200"
                        : "bg-otter-600 text-white hover:bg-otter-700"
                    )}
                  >
                    {copied ? <Check size={16} /> : <Copy size={16} />}
                    {copied ? "Copied" : "Copy link"}
                  </button>
                </div>
                <p className="text-xs text-gray-600">
                  Expires {formatDate(created.expiresAt)}. Copy it now: the full link is only shown once.
                </p>
              </div>
            )}

            {/* Existing links */}
            <div className="space-y-1">
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">
                Existing links
              </p>
              {linksLoading ? (
                <p className="text-sm text-gray-500 text-center py-3">Loading links...</p>
              ) : linksError ? (
                <p className="text-sm text-red-600 text-center py-3">Could not load existing links.</p>
              ) : links.length === 0 ? (
                <p className="text-sm text-gray-500 text-center py-3">No links yet</p>
              ) : (
                <ul className="divide-y divide-gray-100 max-h-56 overflow-y-auto">
                  {links.map((link) => (
                    <LinkRow
                      key={link.id}
                      link={link}
                      isRevoking={revokeMutation.isPending && revokeMutation.variables === link.id}
                      onRevoke={() => revokeMutation.mutate(link.id)}
                    />
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function LinkRow({
  link,
  isRevoking,
  onRevoke,
}: Readonly<{ link: FolderShareLink; isRevoking: boolean; onRevoke: () => void }>) {
  const style = STATUS_STYLES[link.status] ?? STATUS_STYLES.expired;
  const when =
    link.status === "revoked" && link.revokedAt
      ? `Revoked ${formatDate(link.revokedAt)}`
      : link.status === "expired"
        ? `Expired ${formatDate(link.expiresAt)}`
        : `Expires ${formatDate(link.expiresAt)}`;
  return (
    <li data-testid="folder-share-link-row" className="flex items-center justify-between py-2 gap-3">
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-8 h-8 rounded-full bg-otter-100 flex items-center justify-center text-otter-700 flex-shrink-0">
          <Clock size={14} />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-medium text-gray-900 truncate">
            Created {formatDate(link.createdAt)}
          </p>
          <p className="text-xs text-gray-500 truncate">{when}</p>
        </div>
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        <span className={cn("text-xs px-2 py-1 rounded-full", style.className)}>{style.label}</span>
        {link.status === "active" && (
          <button
            onClick={onRevoke}
            disabled={isRevoking}
            className={cn(
              "px-2 py-1 text-xs rounded-md transition",
              isRevoking ? "opacity-50 cursor-wait" : "text-red-600 hover:bg-red-50"
            )}
          >
            {isRevoking ? "Revoking..." : "Revoke"}
          </button>
        )}
      </div>
    </li>
  );
}
