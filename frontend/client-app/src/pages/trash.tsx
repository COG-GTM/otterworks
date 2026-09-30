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
import { documentsApi, filesApi } from "@/lib/api";
import { formatFileSize, formatRelativeTime } from "@/lib/utils";
import toast from "react-hot-toast";
import type { Document, FileItem } from "@/types";

type TrashEntry =
  | { kind: "file"; id: string; name: string; trashedAt?: string; item: FileItem }
  | { kind: "document"; id: string; name: string; trashedAt?: string; item: Document };

export default function TrashPage() {
  return (
    <AppShell>
      <ErrorBoundary>
        <TrashContent />
      </ErrorBoundary>
    </AppShell>
  );
}

function toFileEntry(item: FileItem): TrashEntry {
  return { kind: "file", id: item.id, name: item.name, trashedAt: item.trashedAt, item };
}

function toDocumentEntry(item: Document): TrashEntry {
  return {
    kind: "document",
    id: item.id,
    name: item.title,
    trashedAt: item.deletedAt ?? item.trashedAt ?? undefined,
    item,
  };
}

function byNewestTrashed(a: TrashEntry, b: TrashEntry) {
  const aTime = a.trashedAt ? Date.parse(a.trashedAt) : 0;
  const bTime = b.trashedAt ? Date.parse(b.trashedAt) : 0;
  return bTime - aTime;
}

async function purgeAll<T extends { id: string }>(
  fetchPage: (page: number, pageSize: number) => Promise<{ data: T[] }>,
  purge: (id: string) => Promise<void>,
) {
  const pageSize = 50;
  let batch = await fetchPage(1, pageSize);
  while (batch.data.length > 0) {
    await Promise.all(batch.data.map((item) => purge(item.id)));
    batch = await fetchPage(1, pageSize);
  }
}

function TrashContent() {
  const queryClient = useQueryClient();
  const [deleteTarget, setDeleteTarget] = useState<TrashEntry | null>(null);
  const [showEmptyTrashConfirm, setShowEmptyTrashConfirm] = useState(false);

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["files"] });
    queryClient.invalidateQueries({ queryKey: ["documents"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    queryClient.invalidateQueries({ queryKey: ["storage", "usage"] });
  };

  const filesQuery = useQuery({
    queryKey: ["files", "trash"],
    queryFn: () => filesApi.getTrashed(),
  });

  const documentsQuery = useQuery({
    queryKey: ["documents", "trash"],
    queryFn: () => documentsApi.getTrashed(),
  });

  const restoreMutation = useMutation({
    mutationFn: async (entry: TrashEntry) => {
      if (entry.kind === "document") {
        await documentsApi.restore(entry.id);
      } else {
        await filesApi.restore(entry.id);
      }
      return entry;
    },
    onSuccess: (entry) => {
      invalidateAll();
      toast.success(entry.kind === "document" ? "Document restored" : "File restored");
    },
    onError: (_error, entry) =>
      toast.error(entry.kind === "document" ? "Failed to restore document" : "Failed to restore file"),
  });

  const permanentDeleteMutation = useMutation({
    mutationFn: async (entry: TrashEntry) => {
      if (entry.kind === "document") {
        await documentsApi.permanentDelete(entry.id);
      } else {
        await filesApi.permanentDelete(entry.id);
      }
      return entry;
    },
    onSuccess: (entry) => {
      invalidateAll();
      toast.success(
        entry.kind === "document" ? "Document permanently deleted" : "File permanently deleted",
      );
    },
    onError: (_error, entry) =>
      toast.error(entry.kind === "document" ? "Failed to delete document" : "Failed to delete file"),
  });

  const fileItems = filesQuery.data?.data ?? [];
  const documentItems = documentsQuery.data?.data ?? [];
  const items: TrashEntry[] = [
    ...fileItems.map(toFileEntry),
    ...documentItems.map(toDocumentEntry),
  ].sort(byNewestTrashed);

  const totalTrashed =
    (filesQuery.data?.total ?? fileItems.length) +
    (documentsQuery.data?.total ?? documentItems.length);
  const isLoading = filesQuery.isLoading || documentsQuery.isLoading;

  const emptyTrashMutation = useMutation({
    mutationFn: async () => {
      await Promise.all([
        purgeAll(filesApi.getTrashed, filesApi.permanentDelete),
        purgeAll(documentsApi.getTrashed, documentsApi.permanentDelete),
      ]);
    },
    onSuccess: () => {
      invalidateAll();
      toast.success("Trash emptied");
    },
    onError: () => toast.error("Failed to empty trash"),
  });

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Trash</h1>
          <p className="text-sm text-gray-500 mt-1">
            Items in trash will be permanently deleted after 30 days
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
            Items in trash are automatically deleted after 30 days. Restore items to keep them.
          </p>
        </div>
      )}

      {/* Trash items */}
      {isLoading ? (
        <PageLoader />
      ) : items.length === 0 ? (
        <EmptyState
          icon={Trash2}
          title="Trash is empty"
          description="Deleted files and documents will appear here"
        />
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100 overflow-hidden">
          {items.map((entry) => (
            <TrashRow
              key={`${entry.kind}-${entry.id}`}
              entry={entry}
              onRestore={() => restoreMutation.mutate(entry)}
              onDelete={() => setDeleteTarget(entry)}
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

function getTrashIcon(entry: TrashEntry) {
  if (entry.kind === "document") return FileText;
  const item = entry.item;
  if (item.isFolder) return Folder;
  if (item.mimeType.startsWith("image/")) return Image;
  if (item.mimeType.startsWith("video/")) return Film;
  if (item.mimeType === "application/pdf" || item.mimeType.includes("document"))
    return FileText;
  return File;
}

function describeEntry(entry: TrashEntry) {
  if (entry.kind === "document") {
    const words = entry.item.wordCount ?? 0;
    return `Document \u00B7 ${words} word${words === 1 ? "" : "s"}`;
  }
  return entry.item.isFolder ? "Folder" : formatFileSize(entry.item.size);
}

function TrashRow({
  entry,
  onRestore,
  onDelete,
  isRestoring,
}: Readonly<{
  entry: TrashEntry;
  onRestore: () => void;
  onDelete: () => void;
  isRestoring: boolean;
}>) {
  const Icon = getTrashIcon(entry);

  return (
    <div className="flex items-center gap-4 px-5 py-4 hover:bg-gray-50 transition">
      <div className="w-10 h-10 rounded-lg bg-gray-100 flex items-center justify-center flex-shrink-0">
        <Icon size={20} className="text-gray-400" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 truncate">{entry.name}</p>
        <p className="text-xs text-gray-500">
          {describeEntry(entry)}
          {entry.trashedAt && ` \u00B7 Deleted ${formatRelativeTime(entry.trashedAt)}`}
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
          Delete
        </button>
      </div>
    </div>
  );
}
