import { http, HttpResponse } from "msw";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { NotificationBell } from "./notification-bell";
import { billingServer as server } from "../../test-setup";

const UNREAD_COUNT_URL = "http://localhost:3000/api/v1/notifications/unread-count";

// Same shape as notification-service's UnreadCountResponse.
function respondWithUnreadCount(unreadCount: number) {
  server.use(
    http.get(UNREAD_COUNT_URL, () => HttpResponse.json({ userId: "user-1", unreadCount }))
  );
}

function renderBell() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("NotificationBell", () => {
  it("shows the unread count returned by the notification service", async () => {
    respondWithUnreadCount(3);
    renderBell();
    expect(await screen.findByText("3")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAccessibleName("Notifications (3 unread)");
  });

  it("caps the badge at 99+", async () => {
    respondWithUnreadCount(150);
    renderBell();
    expect(await screen.findByText("99+")).toBeInTheDocument();
  });

  it("shows no badge when there are no unread notifications", async () => {
    respondWithUnreadCount(0);
    renderBell();
    expect(await screen.findByRole("link", { name: "Notifications" })).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });
});
