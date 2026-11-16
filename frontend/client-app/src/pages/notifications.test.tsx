import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import type { Notification } from "@/types";

vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

const list = vi.fn();
vi.mock("@/lib/api", () => ({
  notificationsApi: {
    list: () => list(),
    markRead: vi.fn(),
    markAllRead: vi.fn(),
  },
}));

import NotificationsPage from "./notifications";

function hoursAgo(hours: number): string {
  return new Date(Date.now() - hours * 3_600_000).toISOString();
}

function startOfTodayOffset(dayOffset: number, hour: number): string {
  const d = new Date();
  d.setHours(hour, 0, 0, 0);
  d.setDate(d.getDate() + dayOffset);
  return d.toISOString();
}

function make(id: string, createdAt: string, read: boolean): Notification {
  return { id, type: "system", title: id, message: "", read, createdAt };
}

function renderPage(notifications: Notification[]) {
  list.mockResolvedValue({ data: notifications, total: notifications.length });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NotificationsPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

afterEach(() => list.mockReset());

describe("NotificationsPage grouping", () => {
  it("renders Today, Yesterday and Earlier sections and hides empty ones per tab", async () => {
    renderPage([
      make("today-read", hoursAgo(0), true),
      make("yesterday-unread", startOfTodayOffset(-1, 12), false),
      make("earlier-read", startOfTodayOffset(-5, 12), true),
    ]);

    const today = await screen.findByRole("region", { name: "Today" });
    expect(within(today).getByText("today-read")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Yesterday" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Earlier" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Unread/ }));

    expect(screen.getByRole("tab", { name: /Unread/ })).toHaveAttribute("aria-selected", "true");
    const yesterday = screen.getByRole("region", { name: "Yesterday" });
    expect(within(yesterday).getByText("yesterday-unread")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Today" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Earlier" })).not.toBeInTheDocument();
  });

  it("shows an empty state on the Unread tab when everything is read", async () => {
    renderPage([make("today-read", hoursAgo(0), true)]);

    await screen.findByRole("region", { name: "Today" });
    fireEvent.click(screen.getByRole("tab", { name: "Unread" }));

    expect(screen.getByText("No unread notifications")).toBeInTheDocument();
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });
});
