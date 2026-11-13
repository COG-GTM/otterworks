import type { Document, FileItem } from "@/types";

export type StarredFilter = "all" | "files" | "folders" | "documents";
export type StarredSort = "modified" | "name";

export const STARRED_FILTERS: ReadonlyArray<{ value: StarredFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "files", label: "Files" },
  { value: "folders", label: "Folders" },
  { value: "documents", label: "Documents" },
];

export const STARRED_SORTS: ReadonlyArray<{ value: StarredSort; label: string }> = [
  { value: "modified", label: "Last modified" },
  { value: "name", label: "Name (A–Z)" },
];

export const DEFAULT_STARRED_SORT: StarredSort = "modified";

export interface StarredItems {
  files: FileItem[];
  folders: FileItem[];
  documents: Document[];
}

export interface StarredView {
  files: FileItem[];
  documents: Document[];
}

const nameCollator = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });

function timestamp(value: string | undefined): number {
  const t = value ? Date.parse(value) : Number.NaN;
  return Number.isNaN(t) ? Number.NEGATIVE_INFINITY : t;
}

function sortBy<T>(items: readonly T[], sort: StarredSort, getName: (item: T) => string, getUpdated: (item: T) => string): T[] {
  return [...items].sort((a, b) => {
    if (sort === "modified") {
      const ta = timestamp(getUpdated(a));
      const tb = timestamp(getUpdated(b));
      if (ta !== tb) return tb > ta ? 1 : -1;
    }
    return nameCollator.compare(getName(a) ?? "", getName(b) ?? "");
  });
}

export function sortFileItems(items: readonly FileItem[], sort: StarredSort): FileItem[] {
  return sortBy(items, sort, (f) => f.name, (f) => f.updatedAt);
}

export function sortDocuments(items: readonly Document[], sort: StarredSort): Document[] {
  return sortBy(items, sort, (d) => d.title, (d) => d.updatedAt);
}

/** Applies the type filter and sort order to the starred items shown on the Starred page. */
export function filterAndSortStarred(items: StarredItems, filter: StarredFilter, sort: StarredSort): StarredView {
  const files: FileItem[] = [];
  if (filter === "all" || filter === "files") files.push(...items.files);
  if (filter === "all" || filter === "folders") files.push(...items.folders);
  const documents = filter === "all" || filter === "documents" ? items.documents : [];
  return { files: sortFileItems(files, sort), documents: sortDocuments(documents, sort) };
}

export function starredEmptyTitle(filter: StarredFilter): string {
  return filter === "all" ? "No starred items" : `No starred ${filter}`;
}

export function isStarredFilter(value: string): value is StarredFilter {
  return STARRED_FILTERS.some((f) => f.value === value);
}

export function isStarredSort(value: string): value is StarredSort {
  return STARRED_SORTS.some((s) => s.value === value);
}
