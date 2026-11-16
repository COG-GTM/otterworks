import { describe, it, expect } from "vitest";
import { FILE_TYPE_FILTERS, getFileTypeCategory, matchesFileTypeFilter } from "./file-type";

describe("getFileTypeCategory", () => {
  it.each([
    ["image/png", "image"],
    ["image/jpeg", "image"],
    ["image/svg+xml", "image"],
    ["application/pdf", "pdf"],
    ["text/plain", "document"],
    ["text/markdown", "document"],
    ["text/csv", "document"],
    ["application/msword", "document"],
    ["application/rtf", "document"],
    ["application/vnd.ms-excel", "document"],
    ["application/vnd.ms-powerpoint", "document"],
    ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", "document"],
    ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "document"],
    ["application/vnd.openxmlformats-officedocument.presentationml.presentation", "document"],
    ["application/vnd.oasis.opendocument.text", "document"],
    ["video/mp4", "other"],
    ["audio/mpeg", "other"],
    ["application/zip", "other"],
    ["application/octet-stream", "other"],
    ["application/json", "other"],
  ] as const)("maps %s to %s", (mimeType, expected) => {
    expect(getFileTypeCategory(mimeType)).toBe(expected);
  });

  it("ignores case and MIME parameters", () => {
    expect(getFileTypeCategory("IMAGE/PNG")).toBe("image");
    expect(getFileTypeCategory("Application/PDF")).toBe("pdf");
    expect(getFileTypeCategory("text/plain; charset=utf-8")).toBe("document");
  });

  it("treats missing or empty MIME types as other", () => {
    expect(getFileTypeCategory("")).toBe("other");
    expect(getFileTypeCategory(undefined)).toBe("other");
    expect(getFileTypeCategory(null)).toBe("other");
  });
});

describe("matchesFileTypeFilter", () => {
  it("matches every MIME type when the filter is all", () => {
    for (const mime of ["image/png", "application/pdf", "text/plain", "video/mp4", ""]) {
      expect(matchesFileTypeFilter(mime, "all")).toBe(true);
    }
  });

  it("matches only files in the selected category", () => {
    expect(matchesFileTypeFilter("application/pdf", "pdf")).toBe(true);
    expect(matchesFileTypeFilter("image/png", "pdf")).toBe(false);
    expect(matchesFileTypeFilter("video/mp4", "other")).toBe(true);
    expect(matchesFileTypeFilter("text/plain", "other")).toBe(false);
  });
});

describe("FILE_TYPE_FILTERS", () => {
  it("lists All, Images, PDFs, Documents and Other in order", () => {
    expect(FILE_TYPE_FILTERS.map((f) => f.label)).toEqual([
      "All",
      "Images",
      "PDFs",
      "Documents",
      "Other",
    ]);
  });
});
