import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Notification } from "@/types";
import NotificationsPage from "./notifications";

const { list } = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/api", () => ({
  notificationsApi: { list, markRead: vi.fn(), markAllRead: vi.fn() },
}));

function notification(overrides: Partial<Notification>): Notification {
  return {
    id: "n",
    type: "system",
    title: "Title",
    message: "Message",
    read: true,
    createdAt: new Date().toISOString(),
    ...overrides,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <NotificationsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("NotificationsPage", () => {
  beforeEach(() => {
    list.mockReset();
  });

  it("shows the loader while notifications are loading", () => {
    list.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    expect(screen.queryByText("No notifications")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows the empty state when there are no notifications", async () => {
    list.mockResolvedValue({ data: [], total: 0, page: 1, pageSize: 20, totalPages: 0 });
    renderPage();
    expect(await screen.findByText("No notifications")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading" })).not.toBeInTheDocument();
  });

  it("links document and file notifications to their resource and leaves others unlinked", async () => {
    list.mockResolvedValue({
      data: [
        notification({ id: "1", title: "Doc shared", resourceType: "document", resourceId: "d1" }),
        notification({ id: "2", title: "File shared", resourceType: "file", resourceId: "f1" }),
        notification({ id: "3", title: "Missing id", resourceType: "file" }),
        notification({ id: "4", title: "System notice" }),
      ],
      total: 4,
      page: 1,
      pageSize: 20,
      totalPages: 1,
    });
    renderPage();
    expect(await screen.findByText("Doc shared")).toBeInTheDocument();
    expect(screen.getByText("Doc shared").closest("a")).toHaveAttribute("href", "/documents/d1");
    expect(screen.getByText("File shared").closest("a")).toHaveAttribute("href", "/files/f1");
    expect(screen.getByText("Missing id").closest("a")).toBeNull();
    expect(screen.getByText("System notice").closest("a")).toBeNull();
    expect(screen.queryByText("No notifications")).not.toBeInTheDocument();
  });
});
