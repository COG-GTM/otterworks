import { useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { Share2, LayoutGrid, List, Search, SearchX } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { FileCard } from "@/components/files/file-card";
import { PageLoader } from "@/components/ui/loading-spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { authApi, filesApi } from "@/lib/api";
import {
  ALL_OWNERS,
  EMPTY_SHARED_FILTERS,
  filterSharedFiles,
  getOwnerOptions,
  hasActiveFilters,
  type SharedFilters,
} from "@/lib/shared-filters";
import { useUIStore } from "@/stores/ui-store";
import { cn } from "@/lib/utils";
import type { ViewMode } from "@/types";

export default function SharedPage() {
  return (
    <AppShell>
      <ErrorBoundary>
        <SharedContent />
      </ErrorBoundary>
    </AppShell>
  );
}

function SharedContent() {
  const { viewMode, setViewMode } = useUIStore();

  const { data, isLoading } = useQuery({
    queryKey: ["files", "shared"],
    queryFn: () => filesApi.getAllShared(),
  });

  const rawFiles = data ?? [];
  // Deduplicate by file id (multiple share records for same file)
  const seen = new Set<string>();
  const files = rawFiles.filter((f) => {
    if (seen.has(f.id)) return false;
    seen.add(f.id);
    return true;
  });

  const [filters, setFilters] = useState<SharedFilters>(EMPTY_SHARED_FILTERS);

  const ownerIds = Array.from(new Set(files.map((f) => f.ownerId).filter(Boolean)));
  const ownerLookups = useQueries({
    queries: ownerIds.map((id) => ({
      queryKey: ["users", "by-id", id],
      queryFn: () => authApi.lookupUserById(id),
      staleTime: 5 * 60 * 1000,
      retry: false,
    })),
  });
  const ownerNames: Record<string, string> = {};
  ownerLookups.forEach((lookup, i) => {
    if (lookup.data) {
      ownerNames[ownerIds[i]] = lookup.data.displayName || lookup.data.email;
    }
  });

  const ownerOptions = getOwnerOptions(files, ownerNames);
  const visibleFiles = filterSharedFiles(files, filters);
  const filtersActive = hasActiveFilters(filters);

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Shared with me</h1>
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

      {!isLoading && files.length > 0 && (
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search
              size={16}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
            />
            <input
              type="search"
              aria-label="Search shared files by name"
              value={filters.query}
              onChange={(e) => setFilters((f) => ({ ...f, query: e.target.value }))}
              placeholder="Search by file name..."
              className="w-full pl-9 pr-3 py-2 text-sm bg-white border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-otter-500 focus:border-transparent"
            />
          </div>
          <select
            aria-label="Filter by owner"
            value={filters.ownerId}
            onChange={(e) => setFilters((f) => ({ ...f, ownerId: e.target.value }))}
            className="px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-otter-500"
          >
            <option value={ALL_OWNERS}>All people</option>
            {ownerOptions.map((owner) => (
              <option key={owner.id} value={owner.id}>
                {owner.label}
              </option>
            ))}
          </select>
        </div>
      )}

      {isLoading ? (
        <PageLoader />
      ) : files.length === 0 ? (
        <EmptyState
          icon={Share2}
          title="Nothing shared with you yet"
          description="Files and documents shared with you will appear here"
        />
      ) : visibleFiles.length === 0 && filtersActive ? (
        <EmptyState
          icon={SearchX}
          title="No matches"
          description="No shared files match your search or owner filter"
          action={{
            label: "Clear filters",
            onClick: () => setFilters(EMPTY_SHARED_FILTERS),
          }}
        />
      ) : (
        <div
          className={cn(
            viewMode === "grid"
              ? "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
              : "space-y-1"
          )}
        >
          {visibleFiles.map((file) => (
            <FileCard
              key={file.id}
              file={file}
              view={viewMode}
              onDownload={async (id, name) => {
                try {
                  const downloadUrl = await filesApi.getDownloadUrl(id);
                  const a = document.createElement("a");
                  a.href = downloadUrl;
                  a.download = name;
                  a.rel = "noopener";
                  document.body.appendChild(a);
                  a.click();
                  a.remove();
                  toast.success("File downloaded successfully");
                } catch {
                  toast.error("Download failed. Please try again.");
                }
              }}
            />
          ))}
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
