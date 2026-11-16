import { describe, it, expect } from "vitest";
import {
  DEFAULT_DOCUMENT_SORT,
  DOCUMENT_SORT_OPTIONS,
  filterAndSortDocuments,
  sortDocuments,
} from "./document-sort";

const docs = [
  { id: "1", title: "banana notes", updatedAt: "2026-01-02T10:00:00Z" },
  { id: "2", title: "Apple plan", updatedAt: "2026-03-01T10:00:00Z" },
  { id: "3", title: "cherry roadmap", updatedAt: "2026-02-15T10:00:00Z" },
  { id: "4", title: "Apple budget", updatedAt: "2025-12-31T23:59:59Z" },
];

const ids = (list: { id: string }[]) => list.map((d) => d.id);

describe("sortDocuments", () => {
  it("defaults to last modified, newest first", () => {
    expect(DEFAULT_DOCUMENT_SORT).toBe("updatedAt-desc");
    expect(ids(sortDocuments(docs))).toEqual(["2", "3", "1", "4"]);
  });

  it("sorts by title A-Z, case-insensitively", () => {
    expect(ids(sortDocuments(docs, "title-asc"))).toEqual(["4", "2", "1", "3"]);
  });

  it("sorts by title Z-A, case-insensitively", () => {
    expect(ids(sortDocuments(docs, "title-desc"))).toEqual(["3", "1", "2", "4"]);
  });

  it("orders numbers in titles naturally", () => {
    const numbered = [
      { id: "a", title: "Doc 10", updatedAt: "2026-01-01T00:00:00Z" },
      { id: "b", title: "Doc 2", updatedAt: "2026-01-01T00:00:00Z" },
    ];
    expect(ids(sortDocuments(numbered, "title-asc"))).toEqual(["b", "a"]);
  });

  it("puts documents with invalid dates last when sorting by last modified", () => {
    const withInvalid = [
      { id: "x", title: "x", updatedAt: "not-a-date" },
      ...docs,
    ];
    expect(ids(sortDocuments(withInvalid)).at(-1)).toBe("x");
  });

  it("does not mutate the input array", () => {
    const input = [...docs];
    sortDocuments(input, "title-asc");
    expect(input).toEqual(docs);
  });

  it("handles an empty list", () => {
    expect(sortDocuments([], "title-desc")).toEqual([]);
  });

  it("exposes the three dropdown options with Last modified first", () => {
    expect(DOCUMENT_SORT_OPTIONS.map((o) => o.label)).toEqual([
      "Last modified",
      "Title A-Z",
      "Title Z-A",
    ]);
  });
});

describe("filterAndSortDocuments", () => {
  it("returns all documents sorted when the query is empty", () => {
    expect(ids(filterAndSortDocuments(docs, "", "title-asc"))).toEqual(["4", "2", "1", "3"]);
  });

  it("filters by title case-insensitively and then sorts the matches", () => {
    expect(ids(filterAndSortDocuments(docs, "APPLE", "title-asc"))).toEqual(["4", "2"]);
    expect(ids(filterAndSortDocuments(docs, "apple", "title-desc"))).toEqual(["2", "4"]);
    expect(ids(filterAndSortDocuments(docs, "apple", "updatedAt-desc"))).toEqual(["2", "4"]);
  });

  it("returns an empty list when nothing matches", () => {
    expect(filterAndSortDocuments(docs, "zzz", "title-asc")).toEqual([]);
  });
});
