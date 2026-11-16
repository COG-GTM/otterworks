import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Notification } from "@/types";

const api = vi.hoisted(() => ({
  list: vi.fn(),
  markRead: vi.fn(),
  markAllRead: vi.fn(),
  getUnreadCount: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ notificationsApi: api }));
vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

import NotificationsPage from "./notifications";

let store: Notification[];

function notification(id: string, read: boolean): Notification {
  return {
    id,
    type: "system",
    title: `Notification ${id}`,
    message: `Message ${id}`,
    read,
    createdAt: new Date().toISOString(),
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NotificationsPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  store = [notification("1", false), notification("2", true), notification("3", false)];
  api.list.mockImplementation(async () => ({
    data: store.map((n) => ({ ...n })),
    total: store.length,
    page: 1,
    pageSize: 20,
    hasMore: false,
  }));
  api.markRead.mockImplementation(async (id: string) => {
    store = store.map((n) => (n.id === id ? { ...n, read: true } : n));
  });
});

describe("Notifications page tabs", () => {
  it("shows All and Unread tabs with the unread count", async () => {
    renderPage();
    expect(await screen.findByText("Notification 1")).toBeInTheDocument();
    const allTab = screen.getByRole("tab", { name: /^All/ });
    const unreadTab = screen.getByRole("tab", { name: /^Unread/ });
    expect(allTab).toHaveAttribute("aria-selected", "true");
    expect(within(unreadTab).getByTestId("unread-tab-count")).toHaveTextContent("2");
    expect(screen.getByText("Notification 2")).toBeInTheDocument();
  });

  it("filters to unread notifications and removes one once marked as read", async () => {
    renderPage();
    await screen.findByText("Notification 1");
    fireEvent.click(screen.getByRole("tab", { name: /^Unread/ }));

    expect(screen.getByText("Notification 1")).toBeInTheDocument();
    expect(screen.getByText("Notification 3")).toBeInTheDocument();
    expect(screen.queryByText("Notification 2")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Notification 1"));
    await waitFor(() => expect(screen.queryByText("Notification 1")).not.toBeInTheDocument());
    expect(api.markRead).toHaveBeenCalledWith("1", expect.anything());
    expect(screen.getByTestId("unread-tab-count")).toHaveTextContent("1");
  });

  it("shows \"You're all caught up\" when there are no unread notifications", async () => {
    store = [notification("2", true)];
    renderPage();
    await screen.findByText("Notification 2");
    fireEvent.click(screen.getByRole("tab", { name: /^Unread/ }));
    expect(screen.getByText("You're all caught up")).toBeInTheDocument();
    expect(screen.queryByText("Notification 2")).not.toBeInTheDocument();
  });
});
