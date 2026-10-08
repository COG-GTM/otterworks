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
import { filesApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";
import { formatFileSize, formatRelativeTime } from "@/lib/utils";
import toast from "react-hot-toast";
import type { FileItem } from "@/types";

/// Who deleted an item, from the signed-in user's point of view.
export function deletedByLabel(
  item: Pick<FileItem, "trashedBy" | "trashedByEmail">,
  currentUserId?: string
): string {
  if (currentUserId && item.trashedBy === currentUserId) return "you";
  return item.trashedByEmail ?? "unknown";
}

export default function TrashPage() {
  return (
    <AppShell>
      <ErrorBoundary>
        <RecentlyDeletedContent />
      </ErrorBoundary>
    </AppShell>
  );
}

export function RecentlyDeletedContent() {
  const currentUserId = useAuthStore((state) => state.user?.id);
  const queryClient = useQueryClient();
  const [deleteTarget, setDeleteTarget] = useState<FileItem | null>(null);
  const [showEmptyTrashConfirm, setShowEmptyTrashConfirm] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["files", "trash"],
    queryFn: () => filesApi.getTrashed(),
  });

  const restoreMutation = useMutation({
    mutationFn: filesApi.restore,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["files"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["storage", "usage"] });
      toast.success("File restored");
    },
    onError: () => toast.error("Failed to restore file"),
  });

  const permanentDeleteMutation = useMutation({
    mutationFn: filesApi.permanentDelete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["files"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["storage", "usage"] });
      toast.success("File permanently deleted");
    },
    onError: () => toast.error("Failed to delete file"),
  });

  const items = data?.data || [];

  const totalTrashed = data?.total ?? items.length;

  const emptyTrashMutation = useMutation({
    mutationFn: async () => {
      const pageSize = 50;
      let batch = await filesApi.getTrashed(1, pageSize);
      while (batch.data.length > 0) {
        await Promise.all(batch.data.map((item) => filesApi.permanentDelete(item.id)));
        batch = await filesApi.getTrashed(1, pageSize);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["files"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["storage", "usage"] });
      toast.success("Trash emptied");
    },
    onError: () => toast.error("Failed to empty trash"),
  });

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Recently deleted</h1>
          <p className="text-sm text-gray-500 mt-1">
            Items deleted in the last 30 days. After 30 days they are removed permanently.
          </p>
        </div>
        {items.length > 0 && (
          <button
            onClick={() => setShowEmptyTrashConfirm(true)}
            disabled={emptyTrashMutation.isPending}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-red-600 bg-red-50 rounded-lg hover:bg-red-100 transition disabled:opacity-50"
          >
            <Trash2 size={16} />
            Empty Trash
          </button>
        )}
      </div>

      {/* Warning banner */}
      {items.length > 0 && (
        <div className="flex items-center gap-3 p-4 bg-amber-50 border border-amber-200 rounded-xl">
          <AlertTriangle size={18} className="text-amber-600 flex-shrink-0" />
          <p className="text-sm text-amber-800">
            Items are removed permanently after 30 days. Restore items to keep them.
          </p>
        </div>
      )}

      {/* Trash items */}
      {isLoading ? (
        <PageLoader />
      ) : items.length === 0 ? (
        <EmptyState
          icon={Trash2}
          title="Nothing deleted in the last 30 days"
          description="Files you delete appear here for 30 days, then they are removed permanently"
        />
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100 overflow-hidden">
          {items.map((item) => (
            <TrashRow
              key={item.id}
              item={item}
              deletedBy={deletedByLabel(item, currentUserId)}
              onRestore={() => restoreMutation.mutate(item.id)}
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
          if (deleteTarget) permanentDeleteMutation.mutate(deleteTarget.id);
          setDeleteTarget(null);
        }}
        onCancel={() => setDeleteTarget(null)}
      />

      {/* Confirm empty trash */}
      <ConfirmDialog
        open={showEmptyTrashConfirm}
        title="Empty trash"
        description={`This will permanently delete all ${totalTrashed} item${totalTrashed === 1 ? "" : "s"} in trash. This action cannot be undone.`}
        confirmLabel="Delete all permanently"
        variant="destructive"
        onConfirm={() => {
          emptyTrashMutation.mutate();
          setShowEmptyTrashConfirm(false);
        }}
        onCancel={() => setShowEmptyTrashConfirm(false)}
      />
    </div>
  );
}

function getTrashIcon(item: FileItem) {
  if (item.isFolder) return Folder;
  if (item.mimeType.startsWith("image/")) return Image;
  if (item.mimeType.startsWith("video/")) return Film;
  if (item.mimeType === "application/pdf" || item.mimeType.includes("document"))
    return FileText;
  return File;
}

function TrashRow({
  item,
  deletedBy,
  onRestore,
  onDelete,
  isRestoring,
}: Readonly<{
  item: FileItem;
  deletedBy: string;
  onRestore: () => void;
  onDelete: () => void;
  isRestoring: boolean;
}>) {
  const Icon = getTrashIcon(item);

  return (
    <div className="flex items-center gap-4 px-5 py-4 hover:bg-gray-50 transition">
      <div className="w-10 h-10 rounded-lg bg-gray-100 flex items-center justify-center flex-shrink-0">
        <Icon size={20} className="text-gray-400" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 truncate">{item.name}</p>
        <p className="text-xs text-gray-500">
          {item.isFolder ? "Folder" : formatFileSize(item.size)}
          {item.originalLocation && ` \u00B7 In ${item.originalLocation}`}
          {` \u00B7 Deleted by ${deletedBy}`}
          {item.trashedAt && ` \u00B7 ${formatRelativeTime(item.trashedAt)}`}
        </p>
        {item.originalFolderMissing && (
          <p className="text-xs text-amber-700 mt-0.5">
            {"Original folder was deleted \u2014 restores to My Files"}
          </p>
        )}
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
          Delete
        </button>
      </div>
    </div>
  );
}
