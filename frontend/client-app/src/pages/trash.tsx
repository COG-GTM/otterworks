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

type TrashItem =
  | { kind: "file"; id: string; name: string; deletedAt?: string; file: FileItem }
  | { kind: "document"; id: string; name: string; deletedAt?: string; document: Document };

function toTrashItems(files: FileItem[], documents: Document[]): TrashItem[] {
  const items: TrashItem[] = [
    ...files.map((file): TrashItem => ({
      kind: "file",
      id: file.id,
      name: file.name,
      deletedAt: file.trashedAt ?? file.updatedAt ?? undefined,
      file,
    })),
    ...documents.map((document): TrashItem => ({
      kind: "document",
      id: document.id,
      name: document.title,
      deletedAt: document.deletedAt ?? document.trashedAt,
      document,
    })),
  ];
  return items.sort((a, b) => {
    const aTime = a.deletedAt ? new Date(a.deletedAt).getTime() : 0;
    const bTime = b.deletedAt ? new Date(b.deletedAt).getTime() : 0;
    return bTime - aTime;
  });
}

export default function TrashPage() {
  return (
    <AppShell>
      <ErrorBoundary>
        <TrashContent />
      </ErrorBoundary>
    </AppShell>
  );
}

function TrashContent() {
  const queryClient = useQueryClient();
  const [deleteTarget, setDeleteTarget] = useState<TrashItem | null>(null);
  const [showEmptyTrashConfirm, setShowEmptyTrashConfirm] = useState(false);

  const invalidateAfterChange = () => {
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

  const isLoading = filesQuery.isLoading || documentsQuery.isLoading;

  const restoreMutation = useMutation({
    mutationFn: (item: TrashItem) =>
      item.kind === "file" ? filesApi.restore(item.id) : documentsApi.restore(item.id),
    onSuccess: (_data, item) => {
      invalidateAfterChange();
      toast.success(item.kind === "file" ? "File restored" : "Document restored");
    },
    onError: (_error, item) =>
      toast.error(item.kind === "file" ? "Failed to restore file" : "Failed to restore document"),
  });

  const permanentDeleteMutation = useMutation({
    mutationFn: (item: TrashItem) =>
      item.kind === "file"
        ? filesApi.permanentDelete(item.id)
        : documentsApi.permanentDelete(item.id),
    onSuccess: (_data, item) => {
      invalidateAfterChange();
      toast.success(
        item.kind === "file" ? "File permanently deleted" : "Document permanently deleted",
      );
    },
    onError: (_error, item) =>
      toast.error(item.kind === "file" ? "Failed to delete file" : "Failed to delete document"),
  });

  const items = toTrashItems(filesQuery.data?.data ?? [], documentsQuery.data?.data ?? []);

  const totalTrashed =
    (filesQuery.data?.total ?? filesQuery.data?.data.length ?? 0) +
    (documentsQuery.data?.total ?? documentsQuery.data?.data.length ?? 0);

  const emptyTrashMutation = useMutation({
    mutationFn: async () => {
      const pageSize = 50;
      let fileBatch = await filesApi.getTrashed(1, pageSize);
      while (fileBatch.data.length > 0) {
        await Promise.all(fileBatch.data.map((item) => filesApi.permanentDelete(item.id)));
        fileBatch = await filesApi.getTrashed(1, pageSize);
      }
      let documentBatch = await documentsApi.getTrashed(1, pageSize);
      while (documentBatch.data.length > 0) {
        await Promise.all(
          documentBatch.data.map((item) => documentsApi.permanentDelete(item.id)),
        );
        documentBatch = await documentsApi.getTrashed(1, pageSize);
      }
    },
    onSuccess: () => toast.success("Trash emptied"),
    onError: () => toast.error("Failed to empty trash"),
    onSettled: () => invalidateAfterChange(),
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
          {items.map((item) => (
            <TrashRow
              key={`${item.kind}-${item.id}`}
              item={item}
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

function getTrashIcon(item: TrashItem) {
  if (item.kind === "document") return FileText;
  const file = item.file;
  if (file.isFolder) return Folder;
  if (file.mimeType.startsWith("image/")) return Image;
  if (file.mimeType.startsWith("video/")) return Film;
  if (file.mimeType === "application/pdf" || file.mimeType.includes("document"))
    return FileText;
  return File;
}

function getTrashDescription(item: TrashItem) {
  if (item.kind === "document") {
    const words = item.document.wordCount ?? 0;
    return `Document \u00B7 ${words} word${words === 1 ? "" : "s"}`;
  }
  return item.file.isFolder ? "Folder" : formatFileSize(item.file.size);
}

function TrashRow({
  item,
  onRestore,
  onDelete,
  isRestoring,
}: Readonly<{
  item: TrashItem;
  onRestore: () => void;
  onDelete: () => void;
  isRestoring: boolean;
}>) {
  const Icon = getTrashIcon(item);

  return (
    <div
      className="flex items-center gap-4 px-5 py-4 hover:bg-gray-50 transition"
      data-testid={`trash-row-${item.kind}`}
    >
      <div className="w-10 h-10 rounded-lg bg-gray-100 flex items-center justify-center flex-shrink-0">
        <Icon size={20} className="text-gray-400" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 truncate">{item.name}</p>
        <p className="text-xs text-gray-500">
          {getTrashDescription(item)}
          {item.deletedAt && ` \u00B7 Deleted ${formatRelativeTime(item.deletedAt)}`}
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
