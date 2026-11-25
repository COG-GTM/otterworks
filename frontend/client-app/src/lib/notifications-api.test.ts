import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { notificationsApi } from "./api";
import { billingServer as server } from "../test-setup";

const BASE = "http://localhost:3000/api/v1/notifications";

describe("notificationsApi", () => {
  it("marks one notification read with PUT /notifications/:id/read", async () => {
    let hit = false;
    server.use(
      http.put(`${BASE}/n-1/read`, () => {
        hit = true;
        return new HttpResponse(null, { status: 204 });
      })
    );
    await notificationsApi.markRead("n-1");
    expect(hit).toBe(true);
  });

  it("marks all notifications read with PUT /notifications/read-all", async () => {
    let hit = false;
    server.use(
      http.put(`${BASE}/read-all`, () => {
        hit = true;
        return HttpResponse.json({ marked_count: 3 });
      })
    );
    await notificationsApi.markAllRead();
    expect(hit).toBe(true);
  });

  it("sends the page size as page_size, the parameter the service reads", async () => {
    let query: URLSearchParams | undefined;
    server.use(
      http.get(BASE, ({ request }) => {
        query = new URL(request.url).searchParams;
        return HttpResponse.json({ data: [], total: 0, page: 2, page_size: 5, has_more: false });
      })
    );
    await notificationsApi.list(2, 5);
    expect(query?.get("page")).toBe("2");
    expect(query?.get("page_size")).toBe("5");
  });
});
