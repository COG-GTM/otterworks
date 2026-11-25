import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("./api-client", () => ({
  apiClient: {
    get: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
  },
}));

import { apiClient } from "./api-client";
import { notificationsApi } from "./api";

const client = vi.mocked(apiClient);

// DV-6: notification-service exposes PUT for read state and reads `page_size`.
describe("notificationsApi", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("marks one notification read with PUT /notifications/{id}/read", async () => {
    client.put.mockResolvedValue({ data: undefined });

    await notificationsApi.markRead("n-1");

    expect(client.put).toHaveBeenCalledWith("/notifications/n-1/read");
    expect(client.patch).not.toHaveBeenCalled();
  });

  it("marks all notifications read with PUT /notifications/read-all", async () => {
    client.put.mockResolvedValue({ data: { markedCount: 3 } });

    await notificationsApi.markAllRead();

    expect(client.put).toHaveBeenCalledWith("/notifications/read-all");
    expect(client.post).not.toHaveBeenCalled();
  });

  it("sends the page size as page_size when listing", async () => {
    const page = { data: [], total: 0, page: 2, pageSize: 5, hasMore: false };
    client.get.mockResolvedValue({ data: page });

    const result = await notificationsApi.list(2, 5);

    expect(client.get).toHaveBeenCalledWith("/notifications", {
      params: { page: 2, page_size: 5 },
    });
    expect(result).toEqual(page);
  });
});
