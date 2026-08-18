import { describe, it, expect } from "vitest";
import { getQuotaExceededInfo, DEFAULT_QUOTA_BYTES } from "./api";

function axiosError(status: number, data: unknown) {
  return { response: { status, data } };
}

describe("getQuotaExceededInfo", () => {
  it("parses a 413 quota_exceeded error", () => {
    const err = axiosError(413, {
      error: "quota_exceeded",
      quota_bytes: 10_737_418_240,
      used_bytes: 10_000_000_000,
    });
    expect(getQuotaExceededInfo(err)).toEqual({
      quotaBytes: 10_737_418_240,
      usedBytes: 10_000_000_000,
    });
  });

  it("parses camelCased quota fields", () => {
    const err = axiosError(413, {
      error: "quota_exceeded",
      quotaBytes: 100,
      usedBytes: 99,
    });
    expect(getQuotaExceededInfo(err)).toEqual({ quotaBytes: 100, usedBytes: 99 });
  });

  it("returns null for a 413 without the quota_exceeded error code", () => {
    expect(getQuotaExceededInfo(axiosError(413, { error: "file_too_large" }))).toBeNull();
  });

  it("returns null for non-413 errors", () => {
    expect(getQuotaExceededInfo(axiosError(500, { error: "quota_exceeded" }))).toBeNull();
  });

  it("returns null for errors without a response", () => {
    expect(getQuotaExceededInfo(new Error("network"))).toBeNull();
  });

  it("exposes a 10 GiB default quota", () => {
    expect(DEFAULT_QUOTA_BYTES).toBe(10 * 1024 * 1024 * 1024);
  });
});
