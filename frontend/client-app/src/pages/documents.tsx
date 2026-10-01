import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Plus,
  LayoutGrid,
  List,
  FileText,
  Search,
} from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { DocumentCard } from "@/components/documents/document-card";
import { PageLoader } from "@/components/ui/loading-spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { documentsApi } from "@/lib/api";
import { useUIStore } from "@/stores/ui-store";
import { cn } from "@/lib/utils";
import type { Document, PaginatedResponse, ViewMode } from "@/types";

export default function DocumentsPage() {
  return (
    <AppShell>
      <ErrorBoundary>
        <DocumentsContent />
      </ErrorBoundary>
    </AppShell>
  );
}

function DocumentsContent() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { viewMode, setViewMode } = useUIStore();
  const [searchQuery, setSearchQuery] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["documents", "list"],
    queryFn: () => documentsApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: (title: string) => documentsApi.create(title),
    onSuccess: (doc) => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: ["storage", "usage"] });
      navigate(`/documents/${doc.id}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: documentsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: ["storage", "usage"] });
    },
  });

  const raw = data as PaginatedResponse<Document> & { items?: Document[] } | undefined;
  const documents = raw?.items ?? raw?.data ?? [];
  const filtered = searchQuery
    ? documents.filter((doc) =>
        doc.title.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : documents;

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-bold text-slate-100">Documents</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => createMutation.mutate("Untitled document")}
            disabled={createMutation.isPending}
            className="flex items-center gap-2 px-3 py-2 text-sm text-white bg-otter-500 rounded-lg hover:bg-otter-400 disabled:opacity-50 transition"
          >
            <Plus size={16} />
            New document
          </button>
          <div className="flex items-center border border-line rounded-lg overflow-hidden ml-2">
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
      </div>

      {/* Search/filter */}
      <div className="relative max-w-md">
        <Search
          size={16}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"
        />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Filter documents..."
          className="w-full pl-9 pr-4 py-2 bg-surface-raised border border-line rounded-lg text-sm text-slate-100 placeholder:text-slate-500 hover:border-line-strong focus:outline-none focus:ring-2 focus:ring-otter-400 focus:border-transparent"
        />
      </div>

      {/* Document listing */}
      <DocumentListing
        isLoading={isLoading}
        documents={filtered}
        searchQuery={searchQuery}
        viewMode={viewMode}
        onCreate={() => createMutation.mutate("Untitled document")}
        onDelete={(id) => deleteMutation.mutate(id)}
      />
    </div>
  );
}

function DocumentListing({
  isLoading,
  documents,
  searchQuery,
  viewMode,
  onCreate,
  onDelete,
}: Readonly<{
  isLoading: boolean;
  documents: Document[];
  searchQuery: string;
  viewMode: ViewMode;
  onCreate: () => void;
  onDelete: (id: string) => void;
}>) {
  if (isLoading) {
    return <PageLoader />;
  }

  if (documents.length === 0) {
    return (
      <EmptyState
        icon={FileText}
        title={searchQuery ? "No matching documents" : "No documents yet"}
        description={
          searchQuery
            ? "Try a different search term"
            : "Create your first document to start collaborating"
        }
        action={
          searchQuery
            ? undefined
            : {
                label: "Create document",
                onClick: onCreate,
              }
        }
      />
    );
  }

  return (
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
          onDelete={onDelete}
        />
      ))}
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
          ? "bg-surface-raised text-slate-100"
          : "text-slate-500 hover:text-slate-300 hover:bg-surface-raised"
      )}
    >
      <Icon size={16} />
    </button>
  );
}
