import { describe, it, expect } from "vitest";
import { formatFileSize } from "./utils";

describe("formatFileSize", () => {
  it("keeps existing outputs unchanged", () => {
    expect(formatFileSize(0)).toBe("0 B");
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(1536)).toBe("1.5 KB");
    expect(formatFileSize(10 * 1024 ** 2)).toBe("10 MB");
    expect(formatFileSize(2 * 1024 ** 3)).toBe("2 GB");
    expect(formatFileSize(3 * 1024 ** 4)).toBe("3 TB");
  });

  it("formats petabytes", () => {
    expect(formatFileSize(1024 ** 5)).toBe("1 PB");
    expect(formatFileSize(1.5 * 1024 ** 5)).toBe("1.5 PB");
  });

  it("caps at the largest unit instead of showing undefined", () => {
    expect(formatFileSize(1024 ** 6)).toBe("1024 PB");
    expect(formatFileSize(Number.MAX_VALUE)).not.toContain("undefined");
  });

  it("formats fractional byte values without an undefined unit", () => {
    expect(formatFileSize(0.5)).toBe("0.5 B");
  });

  it.each([-1, -1024, NaN, Infinity, -Infinity])("renders %s as an em dash", (value) => {
    expect(formatFileSize(value)).toBe("\u2014");
  });

  it("renders non-number input as an em dash", () => {
    expect(formatFileSize(undefined as unknown as number)).toBe("\u2014");
    expect(formatFileSize(null as unknown as number)).toBe("\u2014");
  });
});
