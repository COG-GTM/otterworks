import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Trash2,
  RotateCcw,
  AlertTriangle,
  X,
  File,
  FileText,
  Folder,
  Image,
  Film,
} from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { PageLoader } from "@/components/ui/loading-spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { filesApi, authApi } from "@/lib/api";
import { formatFileSize, formatRelativeTime } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";
import toast from "react-hot-toast";
import type { DeletedItem } from "@/types";

export default function RecentlyDeletedPage() {
  return (
    <AppShell>
      <ErrorBoundary>
        <RecentlyDeletedContent />
      </ErrorBoundary>
    </AppShell>
  );
}

function RecentlyDeletedContent() {
  const queryClient = useQueryClient();
  const [deleteTarget, setDeleteTarget] = useState<DeletedItem | null>(null);
  const [showPurgeAllConfirm, setShowPurgeAllConfirm] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["files", "trash"],
    queryFn: () => filesApi.getRecentlyDeleted(),
  });

  const items = data?.data || [];
  const totalDeleted = data?.total ?? items.length;
  const retentionDays = data?.retentionDays ?? 30;

  const deletedByNames = useDeletedByNames(items);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["files"] });
    queryClient.invalidateQueries({ queryKey: ["folders"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    queryClient.invalidateQueries({ queryKey: ["storage", "usage"] });
  };

  const restoreMutation = useMutation({
    mutationFn: (item: DeletedItem) =>
      item.isFolder ? filesApi.restoreFolder(item.id) : filesApi.restore(item.id),
    onSuccess: (_result, item) => {
      invalidate();
      toast.success(
        item.originalLocationExists
          ? `Restored to ${item.originalPath}`
          : "Original folder is gone — restored to the root folder"
      );
    },
    onError: () => toast.error("Failed to restore item"),
  });

  const permanentDeleteMutation = useMutation({
    mutationFn: (item: DeletedItem) =>
      item.isFolder ? filesApi.permanentDeleteFolder(item.id) : filesApi.permanentDelete(item.id),
    onSuccess: () => {
      invalidate();
      toast.success("Item permanently deleted");
    },
    onError: () => toast.error("Failed to delete item"),
  });

  const deleteAllMutation = useMutation({
    mutationFn: async () => {
      const pageSize = 50;
      let batch = await filesApi.getRecentlyDeleted(1, pageSize);
      while (batch.data.length > 0) {
        await Promise.all(
          batch.data.map((item) =>
            item.isFolder
              ? filesApi.permanentDeleteFolder(item.id)
              : filesApi.permanentDelete(item.id)
          )
        );
        batch = await filesApi.getRecentlyDeleted(1, pageSize);
      }
    },
    onSuccess: () => {
      invalidate();
      toast.success("Recently deleted emptied");
    },
    onError: () => toast.error("Failed to empty recently deleted"),
  });

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Recently deleted</h1>
          <p className="text-sm text-gray-500 mt-1">
            Items deleted in the last {retentionDays} days
          </p>
        </div>
        {items.length > 0 && (
          <button
            onClick={() => setShowPurgeAllConfirm(true)}
            disabled={deleteAllMutation.isPending}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-red-600 bg-red-50 rounded-lg hover:bg-red-100 transition disabled:opacity-50"
          >
            <Trash2 size={16} />
            Delete all permanently
          </button>
        )}
      </div>

      {/* Warning banner */}
      {items.length > 0 && (
        <div className="flex items-center gap-3 p-4 bg-amber-50 border border-amber-200 rounded-xl">
          <AlertTriangle size={18} className="text-amber-600 flex-shrink-0" />
          <p className="text-sm text-amber-800">
            Items are permanently purged {retentionDays} days after deletion. Restore items to keep
            them.
          </p>
        </div>
      )}

      {/* Deleted items */}
      {isLoading ? (
        <PageLoader />
      ) : items.length === 0 ? (
        <EmptyState
          icon={Trash2}
          title="Nothing recently deleted"
          description="Files and folders you delete appear here for 30 days"
        />
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100 overflow-hidden">
          {items.map((item) => (
            <DeletedRow
              key={`${item.isFolder ? "folder" : "file"}-${item.id}`}
              item={item}
              deletedByName={item.deletedBy ? deletedByNames[item.deletedBy] : undefined}
              onRestore={() => restoreMutation.mutate(item)}
              onDelete={() => setDeleteTarget(item)}
              isRestoring={restoreMutation.isPending}
            />
          ))}
        </div>
      )}

      {/* Confirm permanent delete of single item */}
      <ConfirmDialog
        open={deleteTarget !== null}
        title="Permanently delete"
        description={`This will permanently delete ${deleteTarget?.name ?? "this item"}. This action cannot be undone.`}
        confirmLabel="Delete permanently"
        variant="destructive"
        onConfirm={() => {
          if (deleteTarget) permanentDeleteMutation.mutate(deleteTarget);
          setDeleteTarget(null);
        }}
        onCancel={() => setDeleteTarget(null)}
      />

      {/* Confirm delete all */}
      <ConfirmDialog
        open={showPurgeAllConfirm}
        title="Delete all permanently"
        description={`This will permanently delete all ${totalDeleted} recently deleted item${totalDeleted === 1 ? "" : "s"}. This action cannot be undone.`}
        confirmLabel="Delete all permanently"
        variant="destructive"
        onConfirm={() => {
          deleteAllMutation.mutate();
          setShowPurgeAllConfirm(false);
        }}
        onCancel={() => setShowPurgeAllConfirm(false)}
      />
    </div>
  );
}

// Deleted-by comes back as a user id; resolve the ids on the page to display names.
function useDeletedByNames(items: DeletedItem[]): Record<string, string> {
  const currentUser = useAuthStore((state) => state.user);
  const ids = Array.from(
    new Set(items.map((item) => item.deletedBy).filter((id): id is string => !!id))
  ).sort((a, b) => a.localeCompare(b));

  const { data } = useQuery({
    queryKey: ["users", "display-names", ids],
    enabled: ids.length > 0,
    queryFn: async () => {
      const entries = await Promise.all(
        ids.map(async (id) => {
          try {
            const user = await authApi.lookupUserById(id);
            return [id, user.displayName || user.email] as const;
          } catch {
            return [id, ""] as const;
          }
        })
      );
      return Object.fromEntries(entries.filter(([, name]) => name)) as Record<string, string>;
    },
  });

  const resolved = { ...(data ?? {}) };
  if (currentUser?.id && !resolved[currentUser.id]) {
    resolved[currentUser.id] = "You";
  }
  return resolved;
}

function getDeletedIcon(item: DeletedItem) {
  if (item.isFolder) return Folder;
  if (item.mimeType.startsWith("image/")) return Image;
  if (item.mimeType.startsWith("video/")) return Film;
  if (item.mimeType === "application/pdf" || item.mimeType.includes("document")) return FileText;
  return File;
}

function DeletedRow({
  item,
  deletedByName,
  onRestore,
  onDelete,
  isRestoring,
}: Readonly<{
  item: DeletedItem;
  deletedByName?: string;
  onRestore: () => void;
  onDelete: () => void;
  isRestoring: boolean;
}>) {
  const Icon = getDeletedIcon(item);

  return (
    <div className="flex items-center gap-4 px-5 py-4 hover:bg-gray-50 transition">
      <div className="w-10 h-10 rounded-lg bg-gray-100 flex items-center justify-center flex-shrink-0">
        <Icon size={20} className="text-gray-400" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 truncate">{item.name}</p>
        <p className="text-xs text-gray-500 truncate">
          {item.isFolder ? "Folder" : formatFileSize(item.size)}
          {` \u00B7 In ${item.originalPath}`}
          {!item.originalLocationExists && " (folder no longer exists)"}
        </p>
        <p className="text-xs text-gray-400 truncate">
          Deleted {item.deletedAt ? formatRelativeTime(item.deletedAt) : "recently"}
          {deletedByName && ` by ${deletedByName}`}
        </p>
      </div>
      <div className="flex items-center gap-1">
        <button
          onClick={onRestore}
          disabled={isRestoring}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-otter-600 bg-otter-50 rounded-lg hover:bg-otter-100 transition disabled:opacity-50"
          title="Restore"
        >
          <RotateCcw size={14} />
          Restore
        </button>
        <button
          onClick={onDelete}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-red-600 bg-red-50 rounded-lg hover:bg-red-100 transition"
          title="Delete permanently"
        >
          <X size={14} />
          Delete permanently
        </button>
      </div>
    </div>
  );
}
