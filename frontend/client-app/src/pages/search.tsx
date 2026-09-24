import { useState, useCallback, useEffect, useMemo, useRef, Suspense } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Search,
  FileText,
  FolderOpen,
  File,
  ChevronDown,
  X,
} from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { PageLoader } from "@/components/ui/loading-spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { searchApi, filesApi } from "@/lib/api";
import { formatRelativeTime, cn } from "@/lib/utils";

/**
 * Strip all HTML tags from a string except {@code <em>} (used by
 * MeiliSearch for search-hit highlighting).  Everything else is
 * escaped to prevent XSS.
 */
function sanitizeSnippet(html: string): string {
  const ALLOWED = /<\/?em>/gi;
  const tokens: string[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = ALLOWED.exec(html)) !== null) {
    if (match.index > lastIndex) {
      tokens.push(escapeHtml(html.slice(lastIndex, match.index)));
    }
    tokens.push(match[0].toLowerCase());
    lastIndex = ALLOWED.lastIndex;
  }
  if (lastIndex < html.length) {
    tokens.push(escapeHtml(html.slice(lastIndex)));
  }
  return tokens.join("");
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
import type { SearchResult } from "@/types";

const TYPE_OPTIONS = [
  { value: "file", label: "Files" },
  { value: "document", label: "Documents" },
  { value: "folder", label: "Folders" },
];

const MIME_OPTIONS = [
  { value: "documents", label: "Documents" },
  { value: "spreadsheets", label: "Spreadsheets" },
  { value: "pdf", label: "PDFs" },
  { value: "images", label: "Images" },
  { value: "video", label: "Videos" },
  { value: "archives", label: "Archives" },
];

const OWNER_OPTIONS = [
  { value: "me", label: "Owned by me" },
  { value: "shared", label: "Shared with me" },
];

const MODIFIED_OPTIONS = [
  { value: "today", label: "Today" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "year", label: "This year" },
];

const FILTER_KEYS = ["type", "owner", "mime", "modified", "folder"] as const;
type FilterKey = (typeof FILTER_KEYS)[number];

// Depth/size caps so the location picker can never fan out unboundedly, plus a
// small concurrency limit to stay under the gateway's rate limit.
const FOLDER_TREE_MAX_DEPTH = 3;
const FOLDER_TREE_MAX_OPTIONS = 200;
const FOLDER_TREE_CONCURRENCY = 4;

type FolderNode = { id: string; label: string };

/** Fetch children in small batches; a failed batch yields no children. */
async function loadChildren(level: FolderNode[]): Promise<FolderNode[]> {
  const children: FolderNode[] = [];
  for (let i = 0; i < level.length; i += FOLDER_TREE_CONCURRENCY) {
    const batch = await Promise.allSettled(
      level.slice(i, i + FOLDER_TREE_CONCURRENCY).map(async (folder) =>
        (await filesApi.listFolders(folder.id)).map((child) => ({
          id: child.id,
          label: `${folder.label} / ${child.name}`,
        }))
      )
    );
    for (const result of batch) {
      if (result.status === "fulfilled") children.push(...result.value);
    }
  }
  return children;
}

/** Flatten the folder tree into "Parent / Child" labelled options. */
async function loadFolderOptions(): Promise<{ value: string; label: string }[]> {
  const options: { value: string; label: string }[] = [];
  let level: FolderNode[] = (await filesApi.listFolders()).map((folder) => ({
    id: folder.id,
    label: folder.name,
  }));

  for (let depth = 0; depth < FOLDER_TREE_MAX_DEPTH && level.length > 0; depth++) {
    for (const folder of level) {
      if (options.length >= FOLDER_TREE_MAX_OPTIONS) return options;
      options.push({ value: folder.id, label: folder.label });
    }
    level = await loadChildren(level);
  }

  return options;
}

function SearchContent() {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlQuery = searchParams.get("q") || "";
  const [query, setQuery] = useState(urlQuery);

  const filters = useMemo(() => {
    const active: Partial<Record<FilterKey, string>> = {};
    for (const key of FILTER_KEYS) {
      const value = searchParams.get(key);
      if (value) active[key] = value;
    }
    return active;
  }, [searchParams]);

  useEffect(() => {
    setQuery(urlQuery);
  }, [urlQuery]);

  const { data: folderOptions = [] } = useQuery({
    queryKey: ["folders", "search-options"],
    queryFn: loadFolderOptions,
  });

  const updateParams = useCallback(
    (changes: Record<string, string | undefined>) => {
      const next = new URLSearchParams(searchParams);
      for (const [key, value] of Object.entries(changes)) {
        if (value) next.set(key, value);
        else next.delete(key);
      }
      setSearchParams(next);
    },
    [searchParams, setSearchParams]
  );

  const { data, isLoading } = useQuery({
    queryKey: ["search", urlQuery, filters],
    queryFn: () =>
      searchApi.search({
        query: urlQuery,
        type: filters.type as "file" | "document" | "folder" | undefined,
        owner: filters.owner,
        mime: filters.mime,
        modified: filters.modified,
        folder: filters.folder,
      }),
    enabled: urlQuery.length > 0,
  });

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      updateParams({ q: query.trim() || undefined });
    },
    [query, updateParams]
  );

  const submittedQuery = urlQuery;
  const results = data?.data || [];
  const hasFilters = Object.keys(filters).length > 0;

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Search</h1>

      {/* Search form */}
      <form onSubmit={handleSubmit} className="relative">
        <Search
          size={20}
          className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400"
        />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search files, documents, and folders..."
          className="w-full pl-12 pr-20 py-3 bg-white border border-gray-300 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-otter-500 focus:border-transparent"
          autoFocus
        />
        <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
          {query && (
            <button
              type="button"
              onClick={() => {
                setQuery("");
                updateParams({ q: undefined });
              }}
              className="p-2 text-gray-400 hover:text-gray-600"
            >
              <X size={16} />
            </button>
          )}
        </div>
      </form>

      {/* Filter chips */}
      <div className="flex flex-wrap items-center gap-2" data-testid="search-filter-chips">
        <FilterChip
          label="Type"
          options={TYPE_OPTIONS}
          value={filters.type}
          onChange={(value) => updateParams({ type: value })}
        />
        <FilterChip
          label="File type"
          options={MIME_OPTIONS}
          value={filters.mime}
          onChange={(value) => updateParams({ mime: value })}
        />
        <FilterChip
          label="People"
          options={OWNER_OPTIONS}
          value={filters.owner}
          onChange={(value) => updateParams({ owner: value })}
        />
        <FilterChip
          label="Modified"
          options={MODIFIED_OPTIONS}
          value={filters.modified}
          onChange={(value) => updateParams({ modified: value })}
        />
        <FilterChip
          label="Location"
          options={folderOptions}
          value={filters.folder}
          onChange={(value) => updateParams({ folder: value })}
        />
        {hasFilters && (
          <button
            type="button"
            onClick={() =>
              updateParams({
                type: undefined,
                mime: undefined,
                owner: undefined,
                modified: undefined,
                folder: undefined,
              })
            }
            className="px-3 py-1.5 text-xs font-medium text-otter-700 hover:underline"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Results */}
      {submittedQuery && isLoading ? (
        <PageLoader />
      ) : submittedQuery && results.length === 0 ? (
        <EmptyState
          icon={Search}
          title="No results found"
          description={`No results for "${submittedQuery}". Try different keywords.`}
        />
      ) : submittedQuery ? (
        <div className="space-y-1">
          <p className="text-sm text-gray-500 mb-4">
            {data?.total || results.length} result{results.length !== 1 ? "s" : ""} for &ldquo;{submittedQuery}&rdquo;
          </p>
          {results.map((result) => (
            <SearchResultRow key={result.id} result={result} />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={Search}
          title="Search OtterWorks"
          description="Find files, documents, and folders across your workspace"
        />
      )}
    </div>
  );
}

interface FilterChipProps {
  label: string;
  options: Array<{ value: string; label: string }>;
  value?: string;
  onChange: (value: string | undefined) => void;
}

function FilterChip({ label, options, value, onChange }: Readonly<FilterChipProps>) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const selected = options.find((option) => option.value === value);

  useEffect(() => {
    if (!open) return;
    const onClickOutside = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={cn(
          "flex items-center gap-1 px-3 py-1.5 rounded-full text-xs font-medium border transition",
          selected
            ? "bg-otter-600 border-otter-600 text-white"
            : "bg-white border-gray-300 text-gray-700 hover:bg-gray-50"
        )}
      >
        {selected ? `${label}: ${selected.label}` : label}
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="absolute z-20 mt-1 min-w-[180px] max-h-64 overflow-auto bg-white border border-gray-200 rounded-lg shadow-lg py-1">
          {options.length === 0 && (
            <p className="px-3 py-2 text-xs text-gray-400">No options</p>
          )}
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => {
                onChange(option.value === value ? undefined : option.value);
                setOpen(false);
              }}
              className={cn(
                "w-full text-left px-3 py-2 text-xs hover:bg-gray-50",
                option.value === value ? "text-otter-700 font-medium" : "text-gray-700"
              )}
            >
              {option.label}
            </button>
          ))}
          {selected && (
            <button
              type="button"
              onClick={() => {
                onChange(undefined);
                setOpen(false);
              }}
              className="w-full text-left px-3 py-2 text-xs text-gray-500 border-t border-gray-100 hover:bg-gray-50"
            >
              Clear
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function SearchResultRow({ result }: Readonly<{ result: SearchResult }>) {
  const href =
    result.type === "document"
      ? `/documents/${result.id}`
      : result.type === "folder"
      ? `/files?folder=${result.id}`
      : `/files/${result.id}`;

  const Icon =
    result.type === "document"
      ? FileText
      : result.type === "folder"
      ? FolderOpen
      : File;

  const iconColor =
    result.type === "document"
      ? "text-blue-600 bg-blue-50"
      : result.type === "folder"
      ? "text-amber-600 bg-amber-50"
      : "text-otter-600 bg-otter-50";

  return (
    <Link
      to={href}
      className="flex items-start gap-4 px-4 py-3 rounded-lg hover:bg-gray-50 transition"
    >
      <div
        className={cn(
          "w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0",
          iconColor
        )}
      >
        <Icon size={20} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900">{result.name}</p>
        {result.snippet && (
          <p
            className="text-xs text-gray-500 mt-0.5 line-clamp-2 [&>em]:font-semibold [&>em]:not-italic [&>em]:text-gray-700"
            dangerouslySetInnerHTML={{
              __html: sanitizeSnippet(result.snippet),
            }}
          />
        )}
        <div className="flex items-center gap-2 mt-1">
          <span className="text-xs text-gray-400">{result.path}</span>
          <span className="text-xs text-gray-300">&middot;</span>
          <span className="text-xs text-gray-400">
            {formatRelativeTime(result.updatedAt)}
          </span>
          <span className="text-xs text-gray-300">&middot;</span>
          <span className="text-xs text-gray-400">{result.ownerName}</span>
        </div>
      </div>
    </Link>
  );
}

export default function SearchPage() {
  return (
    <AppShell>
      <ErrorBoundary>
        <Suspense fallback={<PageLoader />}>
          <SearchContent />
        </Suspense>
      </ErrorBoundary>
    </AppShell>
  );
}
