import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { notificationsApi, toUnreadCount } from "./api";
import { billingServer } from "../test-setup";

describe("toUnreadCount", () => {
  it("reads unreadCount from the notification-service response", () => {
    expect(toUnreadCount({ userId: "u-1", unreadCount: 3 })).toBe(3);
  });

  it("falls back to 0 for missing, malformed or negative counts", () => {
    expect(toUnreadCount(undefined)).toBe(0);
    expect(toUnreadCount(null)).toBe(0);
    expect(toUnreadCount({ userId: "u-1" })).toBe(0);
    expect(toUnreadCount({ count: 5 } as never)).toBe(0);
    expect(toUnreadCount({ userId: "u-1", unreadCount: Number.NaN })).toBe(0);
    expect(toUnreadCount({ userId: "u-1", unreadCount: -1 })).toBe(0);
  });
});

describe("notificationsApi.getUnreadCount", () => {
  it("returns unreadCount from GET /notifications/unread-count", async () => {
    billingServer.use(
      http.get("*/api/v1/notifications/unread-count", () =>
        HttpResponse.json({ userId: "u-1", unreadCount: 7 }),
      ),
    );

    await expect(notificationsApi.getUnreadCount()).resolves.toBe(7);
  });

  it("maps a snake_case unread_count through the camelCase interceptor", async () => {
    billingServer.use(
      http.get("*/api/v1/notifications/unread-count", () =>
        HttpResponse.json({ user_id: "u-1", unread_count: 2 }),
      ),
    );

    await expect(notificationsApi.getUnreadCount()).resolves.toBe(2);
  });
});
