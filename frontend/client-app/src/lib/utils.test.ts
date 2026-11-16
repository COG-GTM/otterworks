import { describe, it, expect } from "vitest";
import { getInitials } from "./utils";

describe("getInitials", () => {
  it("returns the first letters of the first two words", () => {
    expect(getInitials("Ana Lopez")).toBe("AL");
    expect(getInitials("ana maria lopez")).toBe("AM");
  });

  it("returns a single letter for a single-word name", () => {
    expect(getInitials("Ana")).toBe("A");
    expect(getInitials("  ana  ")).toBe("A");
  });

  it("ignores extra spaces between and around words", () => {
    expect(getInitials("  Ana   Lopez ")).toBe("AL");
    expect(getInitials("Ana\t Lopez")).toBe("AL");
  });

  it("falls back to the first letter of the email when the name is empty", () => {
    expect(getInitials("", "zoe@example.com")).toBe("Z");
  });

  it("falls back to the first letter of the email when the name is whitespace-only", () => {
    expect(getInitials("   ", "zoe@example.com")).toBe("Z");
    expect(getInitials(" \t ", "  zoe@example.com")).toBe("Z");
  });

  it("returns ? when the name is empty and there is no email", () => {
    expect(getInitials("")).toBe("?");
    expect(getInitials("   ")).toBe("?");
    expect(getInitials("", "")).toBe("?");
    expect(getInitials("  ", "   ")).toBe("?");
    expect(getInitials(undefined, null)).toBe("?");
  });

  it("prefers the name over the email when the name is present", () => {
    expect(getInitials("Ana Lopez", "zoe@example.com")).toBe("AL");
  });
});
