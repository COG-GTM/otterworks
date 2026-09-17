import { describe, it, expect } from "vitest";
import { safeHttpUrl } from "./utils";

describe("safeHttpUrl", () => {
  it("accepts http(s) and relative URLs", () => {
    expect(safeHttpUrl("https://cdn.example.com/f.pdf")).toBe("https://cdn.example.com/f.pdf");
    expect(safeHttpUrl("/api/v1/files/1/download")).toContain("/api/v1/files/1/download");
  });

  it("rejects script-bearing and malformed URLs", () => {
    expect(safeHttpUrl("javascript:alert(1)")).toBeNull();
    expect(safeHttpUrl("data:text/html,<script>alert(1)</script>")).toBeNull();
    expect(safeHttpUrl("")).toBeNull();
    expect(safeHttpUrl(null)).toBeNull();
  });
});
