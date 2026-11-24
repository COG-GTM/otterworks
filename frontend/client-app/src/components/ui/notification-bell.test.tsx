import { http, HttpResponse } from "msw";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { NotificationBell } from "./notification-bell";
import { billingServer } from "../../test-setup";

function renderBell(unreadCount: number) {
  billingServer.use(
    http.get("*/api/v1/notifications/unread-count", () =>
      HttpResponse.json({ userId: "u-1", unreadCount }),
    ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("NotificationBell", () => {
  it("shows the unread badge and aria-label from the API's unreadCount", async () => {
    renderBell(3);

    expect(await screen.findByLabelText("Notifications (3 unread)")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("caps the badge at 99+", async () => {
    renderBell(150);

    expect(await screen.findByText("99+")).toBeInTheDocument();
  });

  it("shows no badge when there are no unread notifications", async () => {
    renderBell(0);

    const link = await screen.findByRole("link", { name: "Notifications" });
    expect(link).toBeInTheDocument();
    expect(link.querySelector("span")).toBeNull();
  });
});
