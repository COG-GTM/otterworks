import { describe, expect, it } from "vitest";
import { formatFileSize } from "./utils";

describe("formatFileSize", () => {
  it.each([
    [0, "0 B"],
    [512, "512 B"],
    [1024, "1 KB"],
    [1536, "1.5 KB"],
    [1048576, "1 MB"],
    [5 * 1024 ** 3, "5 GB"],
    [1.25 * 1024 ** 4, "1.3 TB"],
  ])("formats %d bytes as %s", (bytes, expected) => {
    expect(formatFileSize(bytes)).toBe(expected);
  });
});
