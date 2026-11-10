import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X, Link2, Copy, Check, AlertCircle, Clock } from "lucide-react";
import toast from "react-hot-toast";
import { shareLinksApi } from "@/lib/api";
import {
  defaultExpiryValue,
  expiryOptions,
  formatDuration,
  formatExpiresAt,
  NEVER_EXPIRES,
  shareLinkErrorMessage,
  toExpiryRequest,
  type ExpiryOption,
} from "@/lib/share-links";
import { cn, formatRelativeTime } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import type { CreatedFolderShareLink, FolderShareLink, ShareLinkStatus } from "@/types";

// Copy is kept here so it can be adjusted once the UX sub-task (OTW-37) lands.
const COPY = {
  title: (name: string) => `Share \u201c${name}\u201d`,
  intro: "Anyone with the link can view the documents in this folder (read-only) until it expires.",
  expiryLabel: "Link expires after",
  create: "Create link",
  creating: "Creating\u2026",
  newLinkHeading: "New link",
  newLinkHint: "Copy this link now. For security it is only shown once.",
  copy: "Copy link",
  copied: "Copied",
  linksHeading: "Links for this folder",
  noLinks: "No links yet.",
  policyError: "Sharing settings could not be loaded.",
  linksError: "Share links could not be loaded.",
  retry: "Retry",
  changeExpiry: "Change expiry",
  revoke: "Revoke",
  revokeTitle: "Revoke this link?",
  revokeDescription: "People with this link will immediately lose access to the folder.",
  createdByYou: "you",
  status: { active: "Active", expired: "Expired", revoked: "Revoked" } satisfies Record<ShareLinkStatus, string>,
};

const STATUS_STYLES: Record<ShareLinkStatus, string> = {
  active: "bg-green-50 text-green-700 border-green-200",
  expired: "bg-gray-100 text-gray-600 border-gray-200",
  revoked: "bg-red-50 text-red-700 border-red-200",
};

interface FolderShareDialogProps {
  folderId: string;
  folderName: string;
  onClose: () => void;
}

export function FolderShareDialog({ folderId, folderName, onClose }: FolderShareDialogProps) {
  const queryClient = useQueryClient();
  const linksKey = ["share-links", folderId];

  const policyQuery = useQuery({
    queryKey: ["share-policy"],
    queryFn: shareLinksApi.getPolicy,
  });
  const linksQuery = useQuery({
    queryKey: linksKey,
    queryFn: () => shareLinksApi.listFolderLinks(folderId),
  });

  const policy = policyQuery.data;
  const options = policy ? expiryOptions(policy) : [];

  const [selectedExpiry, setSelectedExpiry] = useState<string | null>(null);
  const expiryValue = selectedExpiry ?? (policy ? defaultExpiryValue(policy) : "");
  const [createdLink, setCreatedLink] = useState<CreatedFolderShareLink | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<FolderShareLink | null>(null);

  const createMutation = useMutation({
    mutationFn: () => shareLinksApi.createFolderLink(folderId, toExpiryRequest(expiryValue)),
    onMutate: () => setError(null),
    onSuccess: (link) => {
      setCreatedLink(link);
      toast.success("Share link created");
      queryClient.invalidateQueries({ queryKey: linksKey });
    },
    onError: (err) => setError(shareLinkErrorMessage(err, "create")),
  });

  const updateMutation = useMutation({
    mutationFn: ({ linkId, value }: { linkId: string; value: string }) =>
      shareLinksApi.updateLink(linkId, toExpiryRequest(value)),
    onMutate: () => setError(null),
    onSuccess: () => {
      toast.success("Expiry updated");
      queryClient.invalidateQueries({ queryKey: linksKey });
    },
    onError: (err) => {
      setError(shareLinkErrorMessage(err, "update"));
      queryClient.invalidateQueries({ queryKey: linksKey });
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (linkId: string) => shareLinksApi.revokeLink(linkId),
    onMutate: () => setError(null),
    onSuccess: (_data, linkId) => {
      toast.success("Link revoked");
      if (createdLink?.id === linkId) setCreatedLink(null);
      queryClient.invalidateQueries({ queryKey: linksKey });
    },
    onError: (err) => setError(shareLinkErrorMessage(err, "revoke")),
  });

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="folder-share-title"
          className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] flex flex-col"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
            <h2 id="folder-share-title" className="text-lg font-semibold text-gray-900 truncate">
              {COPY.title(folderName)}
            </h2>
            <button
              onClick={onClose}
              aria-label="Close"
              className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition"
            >
              <X size={18} />
            </button>
          </div>

          <div className="px-6 py-5 space-y-5 overflow-y-auto">
            <p className="text-sm text-gray-500">{COPY.intro}</p>

            {error && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
              >
                <AlertCircle size={16} className="mt-0.5 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {policyQuery.isError ? (
              <LoadError message={COPY.policyError} onRetry={() => policyQuery.refetch()} />
            ) : (
              <div className="flex items-end gap-2">
                <label className="flex-1 text-sm font-medium text-gray-700">
                  {COPY.expiryLabel}
                  <select
                    value={expiryValue}
                    onChange={(e) => setSelectedExpiry(e.target.value)}
                    disabled={!policy}
                    className="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-otter-500 focus:border-transparent"
                  >
                    {options.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  onClick={() => createMutation.mutate()}
                  disabled={!policy || createMutation.isPending}
                  className="flex items-center gap-2 px-4 py-2 bg-otter-600 text-white rounded-lg hover:bg-otter-700 transition text-sm font-medium disabled:opacity-50"
                >
                  <Link2 size={16} />
                  {createMutation.isPending ? COPY.creating : COPY.create}
                </button>
              </div>
            )}

            {createdLink && <CreatedLinkPanel link={createdLink} />}

            <section>
              <h3 className="text-sm font-medium text-gray-700 mb-2">{COPY.linksHeading}</h3>
              {linksQuery.isError ? (
                <LoadError message={COPY.linksError} onRetry={() => linksQuery.refetch()} />
              ) : linksQuery.isLoading ? (
                <p className="text-sm text-gray-400">Loading&hellip;</p>
              ) : (linksQuery.data ?? []).length === 0 ? (
                <p className="text-sm text-gray-400">{COPY.noLinks}</p>
              ) : (
                <ul className="divide-y divide-gray-100 border border-gray-200 rounded-lg">
                  {(linksQuery.data ?? []).map((link) => (
                    <ShareLinkRow
                      key={link.id}
                      link={link}
                      options={options}
                      busy={
                        (updateMutation.isPending && updateMutation.variables?.linkId === link.id) ||
                        (revokeMutation.isPending && revokeMutation.variables === link.id)
                      }
                      onChangeExpiry={(value) => updateMutation.mutate({ linkId: link.id, value })}
                      onRevoke={() => setRevokeTarget(link)}
                    />
                  ))}
                </ul>
              )}
            </section>
          </div>
        </div>
      </div>
      <ConfirmDialog
        open={revokeTarget !== null}
        title={COPY.revokeTitle}
        description={COPY.revokeDescription}
        confirmLabel={COPY.revoke}
        variant="destructive"
        onConfirm={() => {
          if (revokeTarget) revokeMutation.mutate(revokeTarget.id);
          setRevokeTarget(null);
        }}
        onCancel={() => setRevokeTarget(null)}
      />
    </>
  );
}

function CreatedLinkPanel({ link }: { link: CreatedFolderShareLink }) {
  const [copied, setCopied] = useState(false);
  const url = link.url || `${window.location.origin}/shared-folder/${link.token}`;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      toast.success("Link copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Failed to copy link");
    }
  };

  return (
    <div className="rounded-lg border border-otter-200 bg-otter-50 p-3 space-y-2" data-testid="created-link">
      <p className="text-sm font-medium text-gray-900">{COPY.newLinkHeading}</p>
      <div className="flex items-center gap-2">
        <input
          readOnly
          aria-label="Share link URL"
          value={url}
          onFocus={(e) => e.target.select()}
          className="flex-1 min-w-0 px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white text-gray-700"
        />
        <button
          onClick={handleCopy}
          className="flex items-center gap-2 px-3 py-2 bg-otter-600 text-white rounded-lg hover:bg-otter-700 transition text-sm font-medium"
        >
          {copied ? <Check size={16} /> : <Copy size={16} />}
          {copied ? COPY.copied : COPY.copy}
        </button>
      </div>
      <p className="flex items-center gap-1 text-xs text-gray-600">
        <Clock size={12} />
        {formatExpiresAt(link.expiresAt)}
      </p>
      <p className="text-xs text-gray-500">{COPY.newLinkHint}</p>
    </div>
  );
}

function ShareLinkRow({
  link,
  options,
  busy,
  onChangeExpiry,
  onRevoke,
}: {
  link: FolderShareLink;
  options: ExpiryOption[];
  busy: boolean;
  onChangeExpiry: (value: string) => void;
  onRevoke: () => void;
}) {
  const currentUserId = useAuthStore((s) => s.user?.id);
  const createdBy = link.createdBy === currentUserId ? COPY.createdByYou : link.createdBy.slice(0, 8);
  const isActive = link.status === "active";

  return (
    <li className="px-3 py-3 space-y-2" data-testid={`share-link-${link.id}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm text-gray-900">{formatExpiresAt(link.expiresAt)}</p>
          <p className="text-xs text-gray-500">
            Created {formatRelativeTime(link.createdAt)} by {createdBy}
          </p>
        </div>
        <span
          className={cn(
            "px-2 py-0.5 rounded-full border text-xs font-medium flex-shrink-0",
            STATUS_STYLES[link.status]
          )}
        >
          {COPY.status[link.status]}
        </span>
      </div>
      {isActive && (
        <div className="flex items-center gap-2">
          <select
            aria-label={COPY.changeExpiry}
            value=""
            disabled={busy || options.length === 0}
            onChange={(e) => e.target.value && onChangeExpiry(e.target.value)}
            className="flex-1 px-2 py-1.5 border border-gray-300 rounded-lg text-xs bg-white focus:outline-none focus:ring-2 focus:ring-otter-500"
          >
            <option value="">{COPY.changeExpiry}&hellip;</option>
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.value === NEVER_EXPIRES ? "Never expires" : `${formatDuration(Number(o.value))} from now`}
              </option>
            ))}
          </select>
          <button
            onClick={onRevoke}
            disabled={busy}
            className="px-3 py-1.5 text-xs font-medium text-red-600 border border-red-200 rounded-lg hover:bg-red-50 transition disabled:opacity-50"
          >
            {COPY.revoke}
          </button>
        </div>
      )}
    </li>
  );
}

function LoadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
      <span>{message}</span>
      <button onClick={onRetry} className="font-medium underline">
        {COPY.retry}
      </button>
    </div>
  );
}
