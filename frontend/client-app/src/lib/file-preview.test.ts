import { describe, expect, it } from "vitest";
import { getPreviewKind } from "./file-preview";

describe("getPreviewKind", () => {
  it.each([
    ["image/png", "photo.png", "image"],
    ["image/svg+xml", "logo.svg", "text"],
    ["application/pdf", "report.pdf", "pdf"],
    ["video/mp4", "clip.mp4", "video"],
    ["audio/mpeg", "song.mp3", "audio"],
    ["text/plain", "notes.txt", "text"],
    ["text/csv; charset=utf-8", "data.csv", "text"],
    ["application/json", "config.json", "text"],
    ["application/ld+json", "schema.jsonld", "text"],
  ])("uses the MIME type %s for %s", (mime, name, kind) => {
    expect(getPreviewKind(mime, name)).toBe(kind);
  });

  it.each([
    ["application/octet-stream", "Scan.PDF", "pdf"],
    ["", "main.rs", "text"],
    [undefined, "photo.JPG", "image"],
    ["application/octet-stream", "Dockerfile", "text"],
    ["video/mp2t", "index.ts", "text"],
    ["binary/octet-stream", "voice.m4a", "audio"],
  ])("falls back to the extension when the MIME type is %s (%s)", (mime, name, kind) => {
    expect(getPreviewKind(mime, name)).toBe(kind);
  });

  it.each([
    ["application/zip", "bundle.zip"],
    ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", "spec.docx"],
    ["application/octet-stream", "firmware.bin"],
    ["", "README"],
  ])("reports %s (%s) as unsupported", (mime, name) => {
    expect(getPreviewKind(mime, name)).toBe("unsupported");
  });

  it("treats a .ts file the server serves as an MPEG-TS stream as unsupported", () => {
    expect(getPreviewKind("video/mp2t", "clip.ts", "video/mp2t")).toBe("unsupported");
    expect(getPreviewKind("video/mp2t", "main.ts", "text/plain; charset=utf-8")).toBe("text");
  });
});
