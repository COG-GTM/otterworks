import { describe, it, expect } from "vitest";
import { getTrashRetention, TRASH_RETENTION_DAYS } from "./trash-retention";

const DAY_MS = 24 * 60 * 60 * 1000;
const NOW = new Date("2026-11-13T12:00:00Z");
const daysAgo = (days: number) => new Date(NOW.getTime() - days * DAY_MS).toISOString();

describe("getTrashRetention", () => {
  it("shows days elapsed and days remaining for a normal item", () => {
    expect(getTrashRetention(daysAgo(3), NOW)).toEqual({
      daysLeft: 27,
      deletedLabel: "Deleted 3d ago",
      remainingLabel: "27 days left",
      isUrgent: false,
    });
  });

  it("rounds partial days down so it never overstates the time left", () => {
    const r = getTrashRetention(daysAgo(3.5), NOW);
    expect(r?.deletedLabel).toBe("Deleted 3d ago");
    expect(r?.remainingLabel).toBe("26 days left");
  });

  it("shows 'Deleted today' for items trashed less than a day ago", () => {
    const r = getTrashRetention(daysAgo(0.25), NOW);
    expect(r?.deletedLabel).toBe("Deleted today");
    expect(r?.remainingLabel).toBe("29 days left");
    expect(r?.isUrgent).toBe(false);
  });

  it("is not urgent with 4 days left", () => {
    const r = getTrashRetention(daysAgo(TRASH_RETENTION_DAYS - 4), NOW);
    expect(r?.remainingLabel).toBe("4 days left");
    expect(r?.isUrgent).toBe(false);
  });

  it("is urgent at exactly 3 days left (threshold)", () => {
    const r = getTrashRetention(daysAgo(TRASH_RETENTION_DAYS - 3), NOW);
    expect(r?.daysLeft).toBe(3);
    expect(r?.remainingLabel).toBe("3 days left");
    expect(r?.isUrgent).toBe(true);
  });

  it("uses the singular for 1 day left", () => {
    const r = getTrashRetention(daysAgo(TRASH_RETENTION_DAYS - 1), NOW);
    expect(r?.remainingLabel).toBe("1 day left");
    expect(r?.isUrgent).toBe(true);
  });

  it("shows 'less than a day left' for items due today", () => {
    const r = getTrashRetention(daysAgo(TRASH_RETENTION_DAYS - 0.5), NOW);
    expect(r?.daysLeft).toBe(0);
    expect(r?.remainingLabel).toBe("less than a day left");
    expect(r?.isUrgent).toBe(true);
  });

  it("flags overdue items as pending deletion", () => {
    const r = getTrashRetention(daysAgo(TRASH_RETENTION_DAYS + 2), NOW);
    expect(r?.deletedLabel).toBe("Deleted 32d ago");
    expect(r?.daysLeft).toBeLessThan(0);
    expect(r?.remainingLabel).toBe("pending permanent deletion");
    expect(r?.isUrgent).toBe(true);
  });

  it("returns null when trashedAt is missing or invalid", () => {
    expect(getTrashRetention(undefined, NOW)).toBeNull();
    expect(getTrashRetention(null, NOW)).toBeNull();
    expect(getTrashRetention("", NOW)).toBeNull();
    expect(getTrashRetention("not-a-date", NOW)).toBeNull();
  });
});
