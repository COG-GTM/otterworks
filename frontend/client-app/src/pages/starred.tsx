import { useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { Star, LayoutGrid, List } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { AppShell } from "@/components/layout/app-shell";
import { Breadcrumb } from "@/components/layout/breadcrumb";
import { FileCard } from "@/components/files/file-card";
import { DocumentCard } from "@/components/documents/document-card";
import { PageLoader } from "@/components/ui/loading-spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { filesApi, documentsApi, starredApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";
import { useUIStore } from "@/stores/ui-store";
import { cn } from "@/lib/utils";
import {
  DEFAULT_STARRED_SORT,
  STARRED_FILTERS,
  STARRED_SORTS,
  filterAndSortStarred,
  isStarredSort,
  starredEmptyTitle,
  type StarredFilter,
  type StarredSort,
} from "@/lib/starred-view";
import type { ViewMode } from "@/types";

export default function StarredPage() {
  return (
    <AppShell>
      <ErrorBoundary>
        <StarredContent />
      </ErrorBoundary>
    </AppShell>
  );
}

function StarredContent() {
  const { viewMode, setViewMode } = useUIStore();
  const { user, isLoading: authLoading } = useAuthStore();
  const queryClient = useQueryClient();
  const userId = user?.id ?? "";
  const [filter, setFilter] = useState<StarredFilter>("all");
  const [sort, setSort] = useState<StarredSort>(DEFAULT_STARRED_SORT);

  const { data: starredIds, isLoading: starredIdsLoading } = useQuery({
    queryKey: ["starred", "ids", userId],
    queryFn: () => starredApi.getStarredIds(userId),
    enabled: !!userId,
  });

  const { data: filesData, isLoading: filesLoading } = useQuery({
    queryKey: ["starred", "files", starredIds?.fileIds],
    queryFn: async () => {
      if (!starredIds?.fileIds.length) return [];
      const results = await Promise.allSettled(
        starredIds.fileIds.map((id) => filesApi.get(id))
      );
      return results
        .filter((r): r is PromiseFulfilledResult<Awaited<ReturnType<typeof filesApi.get>>> => r.status === "fulfilled")
        .map((r) => r.value);
    },
    enabled: !!starredIds?.fileIds.length,
    placeholderData: keepPreviousData,
  });

  const { data: foldersData, isLoading: foldersLoading } = useQuery({
    queryKey: ["starred", "folders", starredIds?.folderIds],
    queryFn: async () => {
      if (!starredIds?.folderIds.length) return [];
      const results = await Promise.allSettled(
        starredIds.folderIds.map((id) => filesApi.getFolder(id))
      );
      return results
        .filter((r): r is PromiseFulfilledResult<Awaited<ReturnType<typeof filesApi.getFolder>>> => r.status === "fulfilled")
        .map((r) => r.value);
    },
    enabled: !!starredIds?.folderIds.length,
    placeholderData: keepPreviousData,
  });

  const { data: docsData, isLoading: docsLoading } = useQuery({
    queryKey: ["starred", "documents", starredIds?.documentIds],
    queryFn: async () => {
      if (!starredIds?.documentIds.length) return [];
      const results = await Promise.allSettled(
        starredIds.documentIds.map((id) => documentsApi.get(id))
      );
      return results
        .filter((r): r is PromiseFulfilledResult<Awaited<ReturnType<typeof documentsApi.get>>> => r.status === "fulfilled")
        .map((r) => r.value);
    },
    enabled: !!starredIds?.documentIds.length,
    placeholderData: keepPreviousData,
  });

  const handleStarToggle = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["starred"] });
  }, [queryClient]);

  const { files, documents } = useMemo(
    () =>
      filterAndSortStarred(
        { files: filesData ?? [], folders: foldersData ?? [], documents: docsData ?? [] },
        filter,
        sort
      ),
    [filesData, foldersData, docsData, filter, sort]
  );
  const isLoading = authLoading || starredIdsLoading || filesLoading || foldersLoading || docsLoading;
  const hasAnyStarred = !!(filesData?.length || foldersData?.length || docsData?.length);
  const isEmpty = files.length === 0 && documents.length === 0;

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <Breadcrumb items={[{ label: "Starred" }]} />

      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Starred</h1>
        <div className="flex items-center border border-gray-300 rounded-lg overflow-hidden">
          <ViewBtn
            mode="grid"
            current={viewMode}
            onClick={() => setViewMode("grid")}
            icon={LayoutGrid}
          />
          <ViewBtn
            mode="list"
            current={viewMode}
            onClick={() => setViewMode("list")}
            icon={List}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          role="group"
          aria-label="Filter starred items by type"
          className="flex items-center border border-gray-300 rounded-lg overflow-hidden"
        >
          {STARRED_FILTERS.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={filter === option.value}
              onClick={() => setFilter(option.value)}
              className={cn(
                "px-3 py-1.5 text-sm transition",
                filter === option.value
                  ? "bg-gray-100 text-gray-900 font-medium"
                  : "text-gray-500 hover:text-gray-700 hover:bg-gray-50"
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-500">
          Sort by
          <select
            value={sort}
            onChange={(e) => {
              if (isStarredSort(e.target.value)) setSort(e.target.value);
            }}
            className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm text-gray-900 bg-white"
          >
            {STARRED_SORTS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {isLoading ? (
        <PageLoader />
      ) : isEmpty ? (
        hasAnyStarred ? (
          <EmptyState
            icon={Star}
            title={starredEmptyTitle(filter)}
            description="Try a different filter to see your other starred items."
          />
        ) : (
          <EmptyState
            icon={Star}
            title="No starred items"
            description="Star files and documents for quick access. They will appear here."
          />
        )
      ) : (
        <div className="space-y-8">
          {files.length > 0 && (
            <section>
              <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">
                {filter === "folders" ? "Folders" : "Files"}
              </h2>
              <div
                className={cn(
                  viewMode === "grid"
                    ? "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
                    : "space-y-1"
                )}
              >
                {files.map((file) => (
                  <FileCard
                    key={file.id}
                    file={file}
                    view={viewMode}
                    onStarToggle={handleStarToggle}
                  />
                ))}
              </div>
            </section>
          )}

          {documents.length > 0 && (
            <section>
              <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">
                Documents
              </h2>
              <div
                className={cn(
                  viewMode === "grid"
                    ? "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
                    : "space-y-1"
                )}
              >
                {documents.map((doc) => (
                  <DocumentCard
                    key={doc.id}
                    document={doc}
                    view={viewMode}
                    onStarToggle={handleStarToggle}
                  />
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

function ViewBtn({
  mode,
  current,
  onClick,
  icon: Icon,
}: Readonly<{
  mode: ViewMode;
  current: ViewMode;
  onClick: () => void;
  icon: typeof LayoutGrid;
}>) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "p-2 transition",
        mode === current
          ? "bg-gray-100 text-gray-900"
          : "text-gray-400 hover:text-gray-600 hover:bg-gray-50"
      )}
    >
      <Icon size={16} />
    </button>
  );
}
