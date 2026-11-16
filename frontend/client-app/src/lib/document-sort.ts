import type { Document } from "@/types";

export type DocumentSortOption = "updatedAt-desc" | "title-asc" | "title-desc";

export const DEFAULT_DOCUMENT_SORT: DocumentSortOption = "updatedAt-desc";

export const DOCUMENT_SORT_OPTIONS: ReadonlyArray<{
  value: DocumentSortOption;
  label: string;
}> = [
  { value: "updatedAt-desc", label: "Last modified" },
  { value: "title-asc", label: "Title A-Z" },
  { value: "title-desc", label: "Title Z-A" },
];

type SortableDocument = Pick<Document, "title" | "updatedAt">;

function timestamp(value: string): number {
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? Number.NEGATIVE_INFINITY : time;
}

function compareTitles(a: SortableDocument, b: SortableDocument): number {
  return (a.title ?? "").localeCompare(b.title ?? "", undefined, {
    sensitivity: "base",
    numeric: true,
  });
}

/** Returns a new array sorted by the given option; the input is not mutated. */
export function sortDocuments<T extends SortableDocument>(
  documents: readonly T[],
  sort: DocumentSortOption = DEFAULT_DOCUMENT_SORT
): T[] {
  const sorted = [...documents];
  switch (sort) {
    case "title-asc":
      return sorted.sort(compareTitles);
    case "title-desc":
      return sorted.sort((a, b) => compareTitles(b, a));
    case "updatedAt-desc":
    default:
      return sorted.sort((a, b) => {
        const diff = timestamp(b.updatedAt) - timestamp(a.updatedAt);
        return Number.isNaN(diff) ? 0 : diff;
      });
  }
}

/** Case-insensitive title filter followed by sorting. */
export function filterAndSortDocuments<T extends SortableDocument>(
  documents: readonly T[],
  query: string,
  sort: DocumentSortOption = DEFAULT_DOCUMENT_SORT
): T[] {
  const needle = query.trim().toLowerCase();
  const filtered = needle
    ? documents.filter((doc) => (doc.title ?? "").toLowerCase().includes(needle))
    : documents;
  return sortDocuments(filtered, sort);
}
