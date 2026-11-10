import { describe, expect, it } from "vitest";
import {
  defaultExpiryValue,
  expiryOptions,
  formatDuration,
  formatExpiresAt,
  toExpiryRequest,
} from "./share-links";
import type { SharePolicy } from "@/types";

const DAY = 86400;
const basePolicy: SharePolicy = {
  workspaceId: "default",
  defaultExpirySeconds: 30 * DAY,
  minExpirySeconds: 3600,
  maxExpirySeconds: 365 * DAY,
  allowNever: false,
  updatedBy: null,
  updatedAt: null,
};

describe("share link expiry options", () => {
  it("offers only presets inside the workspace range and marks the default", () => {
    const options = expiryOptions({ ...basePolicy, minExpirySeconds: DAY, maxExpirySeconds: 90 * DAY });
    expect(options.map((o) => o.label)).toEqual(["1 day", "7 days", "30 days (default)", "90 days"]);
  });

  it("offers Never only when the policy allows it", () => {
    expect(expiryOptions(basePolicy).some((o) => o.value === "never")).toBe(false);
    expect(expiryOptions({ ...basePolicy, allowNever: true }).at(-1)).toEqual({ value: "never", label: "Never" });
  });

  it("always includes a non-preset workspace default", () => {
    const options = expiryOptions({ ...basePolicy, defaultExpirySeconds: 14 * DAY });
    expect(options.map((o) => o.value)).toContain(String(14 * DAY));
    expect(options.find((o) => o.value === String(14 * DAY))?.label).toBe("14 days (default)");
    expect(defaultExpiryValue({ ...basePolicy, defaultExpirySeconds: 14 * DAY })).toBe(String(14 * DAY));
  });

  it("maps a choice to the contract request body", () => {
    expect(toExpiryRequest("never")).toEqual({ never: true });
    expect(toExpiryRequest("3600")).toEqual({ expires_in_seconds: 3600 });
  });

  it("formats durations and expiry timestamps", () => {
    expect(formatDuration(3600)).toBe("1 hour");
    expect(formatDuration(2 * 3600)).toBe("2 hours");
    expect(formatDuration(365 * DAY)).toBe("1 year");
    expect(formatExpiresAt(null)).toBe("Never expires");
    expect(formatExpiresAt("2026-12-10T12:00:00Z")).toMatch(/^Expires Dec 10, 2026/);
  });
});
