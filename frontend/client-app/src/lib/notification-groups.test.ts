import { describe, it, expect } from "vitest";
import { groupNotificationsByDay } from "./notification-groups";
import type { Notification } from "@/types";

function notification(id: string, createdAt: Date, read = false): Notification {
  return {
    id,
    type: "system",
    title: `Notification ${id}`,
    message: "",
    read,
    createdAt: createdAt.toISOString(),
  };
}

// Dates are built with local-time constructors so the tests hold in any timezone.
const NOW = new Date(2026, 10, 16, 15, 30, 0);

describe("groupNotificationsByDay", () => {
  it("groups notifications under Today, Yesterday and Earlier in that order", () => {
    const groups = groupNotificationsByDay(
      [
        notification("earlier", new Date(2026, 10, 10, 9, 0)),
        notification("today", new Date(2026, 10, 16, 8, 0)),
        notification("yesterday", new Date(2026, 10, 15, 12, 0)),
      ],
      NOW
    );

    expect(groups.map((g) => g.label)).toEqual(["Today", "Yesterday", "Earlier"]);
    expect(groups.map((g) => g.notifications.map((n) => n.id))).toEqual([
      ["today"],
      ["yesterday"],
      ["earlier"],
    ]);
  });

  it("sorts newest first within each group", () => {
    const groups = groupNotificationsByDay(
      [
        notification("t-morning", new Date(2026, 10, 16, 7, 0)),
        notification("t-afternoon", new Date(2026, 10, 16, 14, 0)),
        notification("t-noon", new Date(2026, 10, 16, 12, 0)),
        notification("e-old", new Date(2026, 9, 1, 12, 0)),
        notification("e-recent", new Date(2026, 10, 12, 12, 0)),
      ],
      NOW
    );

    expect(groups[0].notifications.map((n) => n.id)).toEqual([
      "t-afternoon",
      "t-noon",
      "t-morning",
    ]);
    expect(groups[1].notifications.map((n) => n.id)).toEqual(["e-recent", "e-old"]);
  });

  it("hides groups that have no notifications", () => {
    const groups = groupNotificationsByDay(
      [
        notification("today", new Date(2026, 10, 16, 9, 0)),
        notification("earlier", new Date(2026, 10, 1, 9, 0)),
      ],
      NOW
    );

    expect(groups.map((g) => g.key)).toEqual(["today", "earlier"]);
  });

  it("returns no groups for an empty list", () => {
    expect(groupNotificationsByDay([], NOW)).toEqual([]);
  });

  describe("midnight boundary", () => {
    const justAfterMidnight = new Date(2026, 10, 16, 0, 0, 30);

    it("puts a notification at exactly midnight in Today", () => {
      const groups = groupNotificationsByDay(
        [notification("midnight", new Date(2026, 10, 16, 0, 0, 0, 0))],
        justAfterMidnight
      );
      expect(groups.map((g) => g.key)).toEqual(["today"]);
    });

    it("puts a notification one millisecond before midnight in Yesterday", () => {
      const groups = groupNotificationsByDay(
        [notification("before-midnight", new Date(2026, 10, 15, 23, 59, 59, 999))],
        justAfterMidnight
      );
      expect(groups.map((g) => g.key)).toEqual(["yesterday"]);
    });

    it("splits Yesterday and Earlier at the previous midnight", () => {
      const groups = groupNotificationsByDay(
        [
          notification("start-of-yesterday", new Date(2026, 10, 15, 0, 0, 0, 0)),
          notification("end-of-day-before", new Date(2026, 10, 14, 23, 59, 59, 999)),
        ],
        justAfterMidnight
      );
      expect(groups.map((g) => [g.key, g.notifications.map((n) => n.id)])).toEqual([
        ["yesterday", ["start-of-yesterday"]],
        ["earlier", ["end-of-day-before"]],
      ]);
    });

    it("uses calendar days, not a rolling 24 hours", () => {
      // 1 minute ago but before midnight: Yesterday, even though it is < 24h old.
      const groups = groupNotificationsByDay(
        [notification("late-last-night", new Date(2026, 10, 15, 23, 59, 30))],
        justAfterMidnight
      );
      expect(groups[0].key).toBe("yesterday");
    });

    it("handles month boundaries", () => {
      const firstOfMonth = new Date(2026, 11, 1, 0, 5);
      const groups = groupNotificationsByDay(
        [
          notification("today", new Date(2026, 11, 1, 0, 1)),
          notification("yesterday", new Date(2026, 10, 30, 23, 0)),
          notification("earlier", new Date(2026, 10, 29, 23, 59, 59, 999)),
        ],
        firstOfMonth
      );
      expect(groups.map((g) => [g.key, g.notifications[0].id])).toEqual([
        ["today", "today"],
        ["yesterday", "yesterday"],
        ["earlier", "earlier"],
      ]);
    });
  });
});
