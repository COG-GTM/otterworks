import type { FileItem, Document } from "@/types";

export type RecentItem =
  | { kind: "file"; data: FileItem; updatedAt: string }
  | { kind: "document"; data: Document; updatedAt: string };

export type RecentFilter = "all" | "files" | "documents";

export const RECENT_FILTERS: { value: RecentFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "files", label: "Files" },
  { value: "documents", label: "Documents" },
];

export const TIME_GROUPS = ["Today", "Yesterday", "This week", "Earlier"] as const;

export type TimeGroup = (typeof TIME_GROUPS)[number];

export function buildRecentItems(
  files: FileItem[] | undefined,
  documents: Document[] | undefined
): RecentItem[] {
  const items: RecentItem[] = [];
  for (const file of files ?? []) {
    items.push({ kind: "file", data: file, updatedAt: file.updatedAt });
  }
  for (const doc of documents ?? []) {
    items.push({ kind: "document", data: doc, updatedAt: doc.updatedAt });
  }
  return items.sort(
    (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
  );
}

export function filterRecentItems(
  items: RecentItem[],
  filter: RecentFilter
): RecentItem[] {
  if (filter === "files") return items.filter((item) => item.kind === "file");
  if (filter === "documents") return items.filter((item) => item.kind === "document");
  return items;
}

export function groupByTime(
  items: RecentItem[],
  now: Date = new Date()
): Record<TimeGroup, RecentItem[]> {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  const startOfWeek = new Date(now.getFullYear(), now.getMonth(), now.getDate() - startOfToday.getDay());

  const groups: Record<TimeGroup, RecentItem[]> = {
    Today: [],
    Yesterday: [],
    "This week": [],
    Earlier: [],
  };

  for (const item of items) {
    const d = new Date(item.updatedAt);
    if (d >= startOfToday) {
      groups["Today"].push(item);
    } else if (d >= startOfYesterday) {
      groups["Yesterday"].push(item);
    } else if (d >= startOfWeek) {
      groups["This week"].push(item);
    } else {
      groups["Earlier"].push(item);
    }
  }

  return groups;
}

/** Time groups in display order, with empty groups removed. */
export function nonEmptyGroups(
  groups: Record<TimeGroup, RecentItem[]>
): { label: TimeGroup; items: RecentItem[] }[] {
  return TIME_GROUPS.map((label) => ({ label, items: groups[label] })).filter(
    (group) => group.items.length > 0
  );
}

export function emptyStateTitle(filter: RecentFilter): string {
  if (filter === "files") return "No recent files";
  if (filter === "documents") return "No recent documents";
  return "No recent items";
}

export function emptyStateDescription(filter: RecentFilter): string {
  if (filter === "files") return "Files you open or edit will appear here.";
  if (filter === "documents") return "Documents you open or edit will appear here.";
  return "Files and documents you open or edit will appear here.";
}

export function formatItemCount(count: number): string {
  return `${count} ${count === 1 ? "item" : "items"}`;
}
