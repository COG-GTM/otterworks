import type { FileItem } from "@/types";

export const ALL_OWNERS = "all";

export interface SharedFilters {
  query: string;
  ownerId: string;
}

export interface OwnerOption {
  id: string;
  label: string;
}

export const EMPTY_SHARED_FILTERS: SharedFilters = { query: "", ownerId: ALL_OWNERS };

type SharedFile = Pick<FileItem, "name" | "ownerId" | "ownerName">;

export function ownerLabel(
  file: Pick<FileItem, "ownerId" | "ownerName">,
  ownerNames: Readonly<Record<string, string>> = {}
): string {
  return ownerNames[file.ownerId] || file.ownerName || file.ownerId || "Unknown";
}

// One option per distinct owner, sorted by display label.
export function getOwnerOptions(
  files: readonly SharedFile[],
  ownerNames: Readonly<Record<string, string>> = {}
): OwnerOption[] {
  const byId = new Map<string, string>();
  for (const file of files) {
    if (!file.ownerId || byId.has(file.ownerId)) continue;
    byId.set(file.ownerId, ownerLabel(file, ownerNames));
  }
  return Array.from(byId, ([id, label]) => ({ id, label })).sort((a, b) =>
    a.label.localeCompare(b.label, undefined, { sensitivity: "base" })
  );
}

export function hasActiveFilters(filters: SharedFilters): boolean {
  return filters.query.trim() !== "" || filters.ownerId !== ALL_OWNERS;
}

export function filterSharedFiles<T extends SharedFile>(
  files: readonly T[],
  filters: SharedFilters
): T[] {
  const needle = filters.query.trim().toLowerCase();
  return files.filter(
    (file) =>
      (filters.ownerId === ALL_OWNERS || file.ownerId === filters.ownerId) &&
      (needle === "" || file.name.toLowerCase().includes(needle))
  );
}
