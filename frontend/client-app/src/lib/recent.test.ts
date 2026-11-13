import { describe, it, expect } from "vitest";
import type { Document, FileItem } from "@/types";
import {
  buildRecentItems,
  emptyStateTitle,
  filterRecentItems,
  formatItemCount,
  groupByTime,
  nonEmptyGroups,
} from "./recent";

// Wednesday, 2026-11-11 12:00 local time.
const NOW = new Date(2026, 10, 11, 12, 0, 0);

function at(daysAgo: number, hour = 9): string {
  return new Date(2026, 10, 11 - daysAgo, hour, 0, 0).toISOString();
}

function file(id: string, updatedAt: string): FileItem {
  return { id, name: `${id}.pdf`, updatedAt } as FileItem;
}

function doc(id: string, updatedAt: string): Document {
  return { id, title: id, updatedAt } as Document;
}

const files = [file("f-today", at(0)), file("f-earlier", at(30))];
const docs = [doc("d-yesterday", at(1)), doc("d-week", at(2))];

describe("buildRecentItems", () => {
  it("merges files and documents sorted newest first", () => {
    const items = buildRecentItems(files, docs);
    expect(items.map((i) => i.data.id)).toEqual([
      "f-today",
      "d-yesterday",
      "d-week",
      "f-earlier",
    ]);
    expect(items.map((i) => i.kind)).toEqual(["file", "document", "document", "file"]);
  });

  it("handles missing data", () => {
    expect(buildRecentItems(undefined, undefined)).toEqual([]);
    expect(buildRecentItems(files, undefined)).toHaveLength(2);
  });
});

describe("filterRecentItems", () => {
  const items = buildRecentItems(files, docs);

  it("returns everything for 'all'", () => {
    expect(filterRecentItems(items, "all")).toEqual(items);
  });

  it("returns only files for 'files'", () => {
    const result = filterRecentItems(items, "files");
    expect(result.map((i) => i.data.id)).toEqual(["f-today", "f-earlier"]);
    expect(result.every((i) => i.kind === "file")).toBe(true);
  });

  it("returns only documents for 'documents'", () => {
    const result = filterRecentItems(items, "documents");
    expect(result.map((i) => i.data.id)).toEqual(["d-yesterday", "d-week"]);
    expect(result.every((i) => i.kind === "document")).toBe(true);
  });

  it("returns an empty list when nothing matches the filter", () => {
    const onlyFiles = buildRecentItems(files, []);
    expect(filterRecentItems(onlyFiles, "documents")).toEqual([]);
  });
});

describe("groupByTime with a filter", () => {
  const items = buildRecentItems(files, docs);

  it("groups all items into Today / Yesterday / This week / Earlier", () => {
    const groups = groupByTime(items, NOW);
    expect(groups.Today.map((i) => i.data.id)).toEqual(["f-today"]);
    expect(groups.Yesterday.map((i) => i.data.id)).toEqual(["d-yesterday"]);
    expect(groups["This week"].map((i) => i.data.id)).toEqual(["d-week"]);
    expect(groups.Earlier.map((i) => i.data.id)).toEqual(["f-earlier"]);
  });

  it("hides empty groups after filtering to files", () => {
    const visible = nonEmptyGroups(groupByTime(filterRecentItems(items, "files"), NOW));
    expect(visible.map((g) => g.label)).toEqual(["Today", "Earlier"]);
  });

  it("hides empty groups after filtering to documents", () => {
    const visible = nonEmptyGroups(groupByTime(filterRecentItems(items, "documents"), NOW));
    expect(visible.map((g) => g.label)).toEqual(["Yesterday", "This week"]);
  });

  it("has no visible groups when the filter has no matches", () => {
    const visible = nonEmptyGroups(groupByTime([], NOW));
    expect(visible).toEqual([]);
  });
});

describe("empty state and count copy", () => {
  it("names the filtered kind in the empty state title", () => {
    expect(emptyStateTitle("all")).toBe("No recent items");
    expect(emptyStateTitle("files")).toBe("No recent files");
    expect(emptyStateTitle("documents")).toBe("No recent documents");
  });

  it("pluralizes the item count", () => {
    expect(formatItemCount(0)).toBe("0 items");
    expect(formatItemCount(1)).toBe("1 item");
    expect(formatItemCount(4)).toBe("4 items");
  });
});
