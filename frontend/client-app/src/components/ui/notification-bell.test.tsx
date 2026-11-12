import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { notificationsApi } from "@/lib/api";
import { NotificationBell } from "./notification-bell";

vi.mock("@/lib/api", () => ({
  notificationsApi: { getUnreadCount: vi.fn() },
}));

const getUnreadCount = vi.mocked(notificationsApi.getUnreadCount);

function renderBell() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>
    </QueryClientProvider>
  );
  return client;
}

describe("NotificationBell", () => {
  beforeEach(() => getUnreadCount.mockReset());

  it("labels the link without a count when nothing is unread", async () => {
    getUnreadCount.mockResolvedValue(0);
    const client = renderBell();
    await vi.waitFor(() =>
      expect(client.getQueryState(["notifications", "unread-count"])?.status).toBe("success")
    );
    expect(screen.getByRole("link", { name: "Notifications" })).toHaveAttribute(
      "href",
      "/notifications"
    );
  });

  it("includes the unread count in the accessible label and badge", async () => {
    getUnreadCount.mockResolvedValue(7);
    renderBell();
    expect(await screen.findByRole("link", { name: "Notifications (7 unread)" })).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("caps the badge at 99+ but keeps the exact count in the label", async () => {
    getUnreadCount.mockResolvedValue(150);
    renderBell();
    expect(await screen.findByRole("link", { name: "Notifications (150 unread)" })).toBeInTheDocument();
    expect(screen.getByText("99+")).toBeInTheDocument();
  });
});
