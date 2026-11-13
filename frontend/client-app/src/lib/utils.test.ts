import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { formatRelativeTime } from "./utils";

const NOW = new Date("2026-06-15T12:00:00.000Z");
const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

const offset = (ms: number) => new Date(NOW.getTime() + ms).toISOString();

describe("formatRelativeTime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe("missing or invalid input", () => {
    it.each([
      ["an empty string", ""],
      ["null", null],
      ["undefined", undefined],
      ["an unparseable string", "not-a-date"],
    ])("renders an em dash for %s", (_label, input) => {
      const result = formatRelativeTime(input);
      expect(result).toBe("\u2014");
      expect(result).not.toBe("Invalid Date");
    });
  });

  describe("past timestamps", () => {
    it("shows 'just now' for the current time", () => {
      expect(formatRelativeTime(NOW.toISOString())).toBe("just now");
    });

    it("shows 'just now' under a minute ago", () => {
      expect(formatRelativeTime(offset(-59 * SECOND))).toBe("just now");
    });

    it("shows minutes", () => {
      expect(formatRelativeTime(offset(-5 * MINUTE))).toBe("5m ago");
    });

    it("shows hours", () => {
      expect(formatRelativeTime(offset(-3 * HOUR))).toBe("3h ago");
    });

    it("shows days", () => {
      expect(formatRelativeTime(offset(-2 * DAY))).toBe("2d ago");
    });

    it("shows the date after 7 days", () => {
      const date = offset(-8 * DAY);
      expect(formatRelativeTime(date)).toBe(new Date(date).toLocaleDateString());
    });
  });

  describe("future timestamps", () => {
    it("shows 'just now' under a minute ahead", () => {
      expect(formatRelativeTime(offset(30 * SECOND))).toBe("just now");
    });

    it("shows the date when more than a minute ahead", () => {
      const date = offset(2 * MINUTE);
      expect(formatRelativeTime(date)).toBe(new Date(date).toLocaleDateString());
    });

    it("shows the date for a clock-skewed timestamp days ahead", () => {
      const date = offset(3 * DAY);
      const result = formatRelativeTime(date);
      expect(result).toBe(new Date(date).toLocaleDateString());
      expect(result).not.toBe("just now");
    });
  });
});
