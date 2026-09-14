import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Link2, X } from "lucide-react";
import toast from "react-hot-toast";
import { filesApi } from "@/lib/api";
import { formatRelativeTime } from "@/lib/utils";

interface FolderShareDialogProps {
  folderId: string;
  folderName: string;
  onClose: () => void;
}

function formatExpiry(date: string): string {
  const seconds = Math.round((new Date(date).getTime() - Date.now()) / 1000);
  const absolute = Math.abs(seconds);
  const unit = absolute >= 86_400 ? "day" : absolute >= 3_600 ? "hour" : "minute";
  const divisor = unit === "day" ? 86_400 : unit === "hour" ? 3_600 : 60;
  const value = Math.round(seconds / divisor);
  return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(value, unit);
}

export function FolderShareDialog({
  folderId,
  folderName,
  onClose,
}: FolderShareDialogProps) {
  const queryClient = useQueryClient();
  const [expiresInHours, setExpiresInHours] = useState(24);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const linksQuery = useQuery({
    queryKey: ["folder-share-links", folderId],
    queryFn: () => filesApi.listFolderShareLinks(folderId),
  });

  const createMutation = useMutation({
    mutationFn: () => filesApi.createFolderShareLink(folderId, expiresInHours),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["folder-share-links", folderId] });
      toast.success("Link created");
    },
    onError: () => toast.error("Failed to create link"),
  });

  const revokeMutation = useMutation({
    mutationFn: (linkId: string) => filesApi.revokeFolderShareLink(folderId, linkId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["folder-share-links", folderId] });
      toast.success("Link revoked");
    },
    onError: () => toast.error("Failed to revoke link"),
  });

  const copyLink = async (id: string, url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      setCopiedId(id);
      toast.success("Link copied");
      window.setTimeout(() => setCopiedId(null), 2000);
    } catch {
      toast.error("Failed to copy link");
    }
  };

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div
          className="w-full max-w-lg rounded-2xl bg-white shadow-2xl"
          data-testid="folder-share-dialog"
          onClick={(event) => event.stopPropagation()}
        >
          <header className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
            <div className="flex items-center gap-2">
              <Link2 size={18} className="text-otter-600" />
              <h2 className="text-lg font-semibold text-gray-900">
                Share &ldquo;{folderName}&rdquo;
              </h2>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-1.5 text-gray-400 transition hover:bg-gray-100 hover:text-gray-600"
              aria-label="Close"
            >
              <X size={18} />
            </button>
          </header>

          <div className="space-y-5 px-6 py-5">
            <div className="flex items-end gap-3">
              <label className="flex-1 text-sm font-medium text-gray-700">
                Link expires in
                <select
                  value={expiresInHours}
                  onChange={(event) => setExpiresInHours(Number(event.target.value))}
                  className="mt-1 block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-otter-500 focus:outline-none focus:ring-2 focus:ring-otter-500"
                  data-testid="share-link-expiry"
                >
                  <option value={1}>1 hour</option>
                  <option value={24}>24 hours</option>
                  <option value={168}>7 days</option>
                  <option value={720}>30 days</option>
                </select>
              </label>
              <button
                type="button"
                onClick={() => createMutation.mutate()}
                disabled={createMutation.isPending}
                className="rounded-lg bg-otter-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-otter-700 disabled:cursor-not-allowed disabled:opacity-60"
                data-testid="create-share-link"
              >
                {createMutation.isPending ? "Creating…" : "Create link"}
              </button>
            </div>

            <div>
              <h3 className="mb-2 text-sm font-medium text-gray-700">Active links</h3>
              {linksQuery.isLoading ? (
                <p className="py-5 text-center text-sm text-gray-500">Loading links…</p>
              ) : linksQuery.isError ? (
                <p className="py-5 text-center text-sm text-red-600">Unable to load links</p>
              ) : linksQuery.data?.length ? (
                <div className="space-y-2">
                  {linksQuery.data.map((link) => (
                    <div
                      key={link.id}
                      className="flex items-center gap-3 rounded-lg border border-gray-200 px-3 py-2.5"
                      data-testid="share-link-row"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm text-gray-800" title={link.url}>
                          {link.url}
                        </p>
                        <p className="text-xs text-gray-500">
                          Expires {formatExpiry(link.expiresAt)} · Created{" "}
                          {formatRelativeTime(link.createdAt)}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => copyLink(link.id, link.url)}
                        className="rounded-md p-1.5 text-gray-500 transition hover:bg-otter-50 hover:text-otter-600"
                        aria-label="Copy share link"
                        data-testid="copy-share-link"
                      >
                        {copiedId === link.id ? <Check size={16} /> : <Copy size={16} />}
                      </button>
                      <button
                        type="button"
                        onClick={() => revokeMutation.mutate(link.id)}
                        disabled={revokeMutation.isPending}
                        className="text-xs font-medium text-red-600 hover:text-red-700 disabled:opacity-50"
                        data-testid="revoke-share-link"
                      >
                        Revoke
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="rounded-lg border border-dashed border-gray-300 py-6 text-center text-sm text-gray-500">
                  No active links
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
