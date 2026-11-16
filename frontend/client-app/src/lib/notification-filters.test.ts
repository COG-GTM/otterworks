import { describe, expect, it } from "vitest";
import { countUnread, filterNotifications } from "./notification-filters";
import type { Notification } from "@/types";

function notification(id: string, read: boolean): Notification {
  return {
    id,
    type: "comment",
    title: `Title ${id}`,
    message: `Message ${id}`,
    read,
    createdAt: "2026-01-01T00:00:00Z",
  };
}

const sample = [notification("1", false), notification("2", true), notification("3", false)];

describe("filterNotifications", () => {
  it("returns every notification on the All tab", () => {
    expect(filterNotifications(sample, "all").map((n) => n.id)).toEqual(["1", "2", "3"]);
  });

  it("returns only notifications where read is false on the Unread tab", () => {
    expect(filterNotifications(sample, "unread").map((n) => n.id)).toEqual(["1", "3"]);
  });

  it("drops a notification from Unread once it is marked as read", () => {
    const updated = sample.map((n) => (n.id === "1" ? { ...n, read: true } : n));
    expect(filterNotifications(updated, "unread").map((n) => n.id)).toEqual(["3"]);
  });

  it("returns an empty list on Unread when everything is read", () => {
    const allRead = sample.map((n) => ({ ...n, read: true }));
    expect(filterNotifications(allRead, "unread")).toEqual([]);
  });

  it("handles an empty input", () => {
    expect(filterNotifications([], "all")).toEqual([]);
    expect(filterNotifications([], "unread")).toEqual([]);
  });

  it("does not mutate or return the input array", () => {
    const input = [...sample];
    const result = filterNotifications(input, "all");
    expect(result).not.toBe(input);
    expect(input.map((n) => n.id)).toEqual(["1", "2", "3"]);
  });
});

describe("countUnread", () => {
  it("counts notifications where read is false", () => {
    expect(countUnread(sample)).toBe(2);
    expect(countUnread([])).toBe(0);
    expect(countUnread(sample.map((n) => ({ ...n, read: true })))).toBe(0);
  });
});
