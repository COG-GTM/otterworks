import { describe, it, expect } from "vitest";
import {
  ALL_OWNERS,
  EMPTY_SHARED_FILTERS,
  filterSharedFiles,
  getOwnerOptions,
  hasActiveFilters,
  ownerLabel,
} from "./shared-filters";

const files = [
  { id: "1", name: "Q3 Report.pdf", ownerId: "u-alice", ownerName: "" },
  { id: "2", name: "budget.xlsx", ownerId: "u-bob", ownerName: "" },
  { id: "3", name: "Quarterly REPORT draft.docx", ownerId: "u-bob", ownerName: "" },
  { id: "4", name: "logo.png", ownerId: "u-carol", ownerName: "Carol" },
];

const names = { "u-alice": "Alice", "u-bob": "bob" };

describe("filterSharedFiles", () => {
  it("returns every file when no filters are set", () => {
    expect(filterSharedFiles(files, EMPTY_SHARED_FILTERS)).toEqual(files);
  });

  it("matches file names case-insensitively", () => {
    const ids = filterSharedFiles(files, { query: "report", ownerId: ALL_OWNERS }).map((f) => f.id);
    expect(ids).toEqual(["1", "3"]);
  });

  it("ignores surrounding whitespace in the query", () => {
    const ids = filterSharedFiles(files, { query: "  LOGO ", ownerId: ALL_OWNERS }).map((f) => f.id);
    expect(ids).toEqual(["4"]);
  });

  it("filters by owner", () => {
    const ids = filterSharedFiles(files, { query: "", ownerId: "u-bob" }).map((f) => f.id);
    expect(ids).toEqual(["2", "3"]);
  });

  it("combines the search and owner filters", () => {
    const ids = filterSharedFiles(files, { query: "report", ownerId: "u-bob" }).map((f) => f.id);
    expect(ids).toEqual(["3"]);
  });

  it("returns an empty list when nothing matches", () => {
    expect(filterSharedFiles(files, { query: "missing", ownerId: ALL_OWNERS })).toEqual([]);
    expect(filterSharedFiles(files, { query: "logo", ownerId: "u-alice" })).toEqual([]);
  });

  it("does not mutate the input", () => {
    const copy = [...files];
    filterSharedFiles(files, { query: "report", ownerId: "u-bob" });
    expect(files).toEqual(copy);
  });
});

describe("getOwnerOptions", () => {
  it("lists each owner once, sorted by label", () => {
    expect(getOwnerOptions(files, names)).toEqual([
      { id: "u-alice", label: "Alice" },
      { id: "u-bob", label: "bob" },
      { id: "u-carol", label: "Carol" },
    ]);
  });

  it("falls back to the owner id when no name is known", () => {
    expect(getOwnerOptions([files[0]])).toEqual([{ id: "u-alice", label: "u-alice" }]);
  });

  it("returns no options for an empty list", () => {
    expect(getOwnerOptions([])).toEqual([]);
  });
});

describe("ownerLabel", () => {
  it("prefers resolved names, then ownerName, then ownerId", () => {
    expect(ownerLabel(files[0], names)).toBe("Alice");
    expect(ownerLabel(files[3], names)).toBe("Carol");
    expect(ownerLabel(files[3])).toBe("Carol");
    expect(ownerLabel({ ownerId: "", ownerName: "" })).toBe("Unknown");
  });
});

describe("hasActiveFilters", () => {
  it("is false for the default filters and whitespace-only queries", () => {
    expect(hasActiveFilters(EMPTY_SHARED_FILTERS)).toBe(false);
    expect(hasActiveFilters({ query: "   ", ownerId: ALL_OWNERS })).toBe(false);
  });

  it("is true when a query or owner is set", () => {
    expect(hasActiveFilters({ query: "a", ownerId: ALL_OWNERS })).toBe(true);
    expect(hasActiveFilters({ query: "", ownerId: "u-bob" })).toBe(true);
  });
});
