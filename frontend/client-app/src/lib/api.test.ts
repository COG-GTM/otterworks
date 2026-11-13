import { describe, it, expect } from "vitest";
import { mapRawFile } from "./api";

const base = {
  id: "f1",
  name: "report.pdf",
  mimeType: "application/pdf",
  sizeBytes: 1024,
  s3Key: "k",
  folderId: null,
  ownerId: "u1",
  version: 1,
  createdAt: "2026-10-01T00:00:00Z",
  updatedAt: "2026-11-10T00:00:00Z",
};

describe("mapRawFile trashedAt", () => {
  it("uses updatedAt as the trash time for trashed files", () => {
    expect(mapRawFile({ ...base, isTrashed: true }).trashedAt).toBe("2026-11-10T00:00:00Z");
  });

  it("prefers an explicit trashedAt from the API", () => {
    const file = mapRawFile({ ...base, isTrashed: true, trashedAt: "2026-11-09T00:00:00Z" });
    expect(file.trashedAt).toBe("2026-11-09T00:00:00Z");
  });

  it("leaves trashedAt undefined for files that are not trashed", () => {
    expect(mapRawFile({ ...base, isTrashed: false }).trashedAt).toBeUndefined();
  });
});
