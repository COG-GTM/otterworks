import { describe, it, expect } from "vitest";
import { expiryOptions, formatExpiry } from "./share-link-section";
import type { SharePolicy } from "@/types";

const policy = (overrides: Partial<SharePolicy> = {}): SharePolicy => ({
  workspaceId: "default",
  defaultExpiryDays: 7,
  minExpiryDays: 1,
  maxExpiryDays: 30,
  allowNoExpiry: false,
  ...overrides,
});

describe("OTW-53 share link expiry picker", () => {
  it("AC2/AC3: only offers expiries within workspace bounds", () => {
    expect(expiryOptions(policy())).toEqual([1, 7, 14, 30]);
    expect(expiryOptions(policy({ minExpiryDays: 7, maxExpiryDays: 10 }))).toEqual([7, 10]);
  });

  it("offers all presets when there is no maximum", () => {
    expect(expiryOptions(policy({ maxExpiryDays: null }))).toEqual([1, 7, 14, 30, 90]);
  });

  it("labels links without expiry", () => {
    expect(formatExpiry(null)).toBe("Never expires");
    expect(formatExpiry("2026-11-17T08:00:00Z")).toMatch(/^Expires /);
  });
});
