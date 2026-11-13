import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { Clock } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { FileCard } from "@/components/files/file-card";
import { DocumentCard } from "@/components/documents/document-card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { filesApi, documentsApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  RECENT_FILTERS,
  buildRecentItems,
  emptyStateDescription,
  emptyStateTitle,
  filterRecentItems,
  formatItemCount,
  groupByTime,
  nonEmptyGroups,
  type RecentFilter,
} from "@/lib/recent";

export default function RecentPage() {
  return (
    <AppShell>
      <ErrorBoundary>
        <RecentContent />
      </ErrorBoundary>
    </AppShell>
  );
}

function RecentContent() {
  const { data: recentFiles, isLoading: filesLoading } = useQuery({
    queryKey: ["files", "recent", "all"],
    queryFn: () => filesApi.getRecent(50),
  });

  const { data: recentDocs, isLoading: docsLoading } = useQuery({
    queryKey: ["documents", "recent", "all"],
    queryFn: () => documentsApi.getRecent(50),
  });

  const isLoading = filesLoading || docsLoading;
  const [filter, setFilter] = useState<RecentFilter>("all");

  const allItems = useMemo(
    () => buildRecentItems(recentFiles, recentDocs),
    [recentFiles, recentDocs]
  );

  const filteredItems = useMemo(
    () => filterRecentItems(allItems, filter),
    [allItems, filter]
  );

  const groups = useMemo(
    () => nonEmptyGroups(groupByTime(filteredItems)),
    [filteredItems]
  );

  const totalItems = filteredItems.length;

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Page header */}
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Recent</h1>
          <p className="text-sm text-gray-500 mt-1">
            Files and documents you&apos;ve recently accessed or modified.
            {!isLoading && (
              <span data-testid="recent-count" className="ml-1 text-gray-400">
                &middot; {formatItemCount(totalItems)}
              </span>
            )}
          </p>
        </div>

        <div
          role="group"
          aria-label="Filter recent items"
          className="inline-flex self-start sm:self-auto rounded-lg border border-gray-300 bg-gray-50 p-0.5"
        >
          {RECENT_FILTERS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
              className={cn(
                "px-3 py-1.5 text-sm font-medium rounded-md transition",
                filter === value
                  ? "bg-white text-otter-700 shadow-sm"
                  : "text-gray-600 hover:text-gray-900"
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Loading state */}
      {isLoading && <RecentSkeleton />}

      {/* Empty state */}
      {!isLoading && totalItems === 0 && (
        <EmptyState
          icon={Clock}
          title={emptyStateTitle(filter)}
          description={emptyStateDescription(filter)}
        />
      )}

      {/* Grouped items */}
      {!isLoading &&
        groups.map(({ label, items }) => (
          <section key={label}>
            <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">
              {label}
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {items.map((item) =>
                item.kind === "file" ? (
                  <FileCard
                    key={`file-${item.data.id}`}
                    file={item.data}
                    view="grid"
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
                ) : (
                  <DocumentCard
                    key={`doc-${item.data.id}`}
                    document={item.data}
                    view="grid"
                  />
                )
              )}
            </div>
          </section>
        ))}
    </div>
  );
}

function RecentSkeleton() {
  return (
    <div className="space-y-6">
      {[1, 2].map((section) => (
        <div key={section}>
          <div className="h-4 w-20 bg-gray-200 rounded animate-pulse mb-3" />
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="flex flex-col rounded-xl border border-gray-200 bg-white p-4"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="w-12 h-12 rounded-lg bg-gray-200 animate-pulse" />
                  <div className="w-6 h-6 rounded bg-gray-200 animate-pulse" />
                </div>
                <div className="h-4 w-3/4 bg-gray-200 rounded animate-pulse mb-2" />
                <div className="h-3 w-1/2 bg-gray-200 rounded animate-pulse" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
