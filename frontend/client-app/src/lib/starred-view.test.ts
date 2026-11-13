import { describe, expect, it } from "vitest";
import type { Document, FileItem } from "@/types";
import {
  DEFAULT_STARRED_SORT,
  filterAndSortStarred,
  isStarredFilter,
  isStarredSort,
  starredEmptyTitle,
  type StarredItems,
} from "./starred-view";

function file(id: string, name: string, updatedAt: string, isFolder = false): FileItem {
  return {
    id,
    name,
    mimeType: isFolder ? "inode/directory" : "text/plain",
    size: 0,
    parentId: null,
    ownerId: "u1",
    ownerName: "User",
    isFolder,
    path: `/${name}`,
    sharedWith: [],
    tags: [],
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt,
    versions: [],
  };
}

function doc(id: string, title: string, updatedAt: string): Document {
  return {
    id,
    title,
    content: "",
    ownerId: "u1",
    ownerName: "User",
    parentId: null,
    sharedWith: [],
    collaborators: [],
    tags: [],
    wordCount: 0,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt,
  };
}

const items: StarredItems = {
  files: [
    file("f1", "budget.xlsx", "2026-03-01T00:00:00Z"),
    file("f2", "Agenda.pdf", "2026-05-01T00:00:00Z"),
  ],
  folders: [
    file("d1", "Projects", "2026-04-01T00:00:00Z", true),
    file("d2", "archive", "2026-02-01T00:00:00Z", true),
  ],
  documents: [
    doc("doc1", "Roadmap", "2026-01-15T00:00:00Z"),
    doc("doc2", "Notes", "2026-06-01T00:00:00Z"),
  ],
};

const ids = (list: Array<{ id: string }>) => list.map((i) => i.id);

describe("filterAndSortStarred", () => {
  it("defaults to last modified, newest first", () => {
    expect(DEFAULT_STARRED_SORT).toBe("modified");
    const view = filterAndSortStarred(items, "all", DEFAULT_STARRED_SORT);
    expect(ids(view.files)).toEqual(["f2", "d1", "f1", "d2"]);
    expect(ids(view.documents)).toEqual(["doc2", "doc1"]);
  });

  it("sorts by name A–Z, case-insensitively", () => {
    const view = filterAndSortStarred(items, "all", "name");
    expect(view.files.map((f) => f.name)).toEqual(["Agenda.pdf", "archive", "budget.xlsx", "Projects"]);
    expect(view.documents.map((d) => d.title)).toEqual(["Notes", "Roadmap"]);
  });

  it("filters to files only", () => {
    const view = filterAndSortStarred(items, "files", "modified");
    expect(ids(view.files)).toEqual(["f2", "f1"]);
    expect(view.documents).toEqual([]);
  });

  it("filters to folders only", () => {
    const view = filterAndSortStarred(items, "folders", "name");
    expect(ids(view.files)).toEqual(["d2", "d1"]);
    expect(view.documents).toEqual([]);
  });

  it("filters to documents only", () => {
    const view = filterAndSortStarred(items, "documents", "modified");
    expect(view.files).toEqual([]);
    expect(ids(view.documents)).toEqual(["doc2", "doc1"]);
  });

  it("returns empty lists when a filter has no matches", () => {
    const view = filterAndSortStarred({ ...items, folders: [] }, "folders", "modified");
    expect(view.files).toEqual([]);
    expect(view.documents).toEqual([]);
  });

  it("puts items with a missing or invalid date last and falls back to name", () => {
    const view = filterAndSortStarred(
      {
        files: [file("x", "zeta", ""), file("y", "alpha", "not-a-date"), file("z", "mid", "2026-01-01T00:00:00Z")],
        folders: [],
        documents: [],
      },
      "all",
      "modified"
    );
    expect(ids(view.files)).toEqual(["z", "y", "x"]);
  });

  it("does not mutate the input arrays", () => {
    const original = ids(items.files);
    filterAndSortStarred(items, "all", "name");
    expect(ids(items.files)).toEqual(original);
  });
});

describe("starredEmptyTitle", () => {
  it("names the active filter", () => {
    expect(starredEmptyTitle("all")).toBe("No starred items");
    expect(starredEmptyTitle("files")).toBe("No starred files");
    expect(starredEmptyTitle("folders")).toBe("No starred folders");
    expect(starredEmptyTitle("documents")).toBe("No starred documents");
  });
});

describe("type guards", () => {
  it("accepts only known filter and sort values", () => {
    expect(isStarredFilter("folders")).toBe(true);
    expect(isStarredFilter("images")).toBe(false);
    expect(isStarredSort("name")).toBe(true);
    expect(isStarredSort("size")).toBe(false);
  });
});
