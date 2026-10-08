import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "@/components/layout/sidebar";
import { filesApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";
import type { FileItem, PaginatedResponse, User } from "@/types";
import TrashPageContent, { RecentlyDeletedContent, deletedByLabel } from "./trash";

vi.mock("@/lib/api", () => ({
  filesApi: {
    getTrashed: vi.fn(),
    restore: vi.fn(),
    permanentDelete: vi.fn(),
  },
}));

const CURRENT_USER_ID = "11111111-1111-1111-1111-111111111111";

function makeItem(overrides: Partial<FileItem> = {}): FileItem {
  return {
    id: "file-1",
    name: "quarterly-report.pdf",
    mimeType: "application/pdf",
    size: 2048,
    parentId: null,
    ownerId: CURRENT_USER_ID,
    ownerName: "",
    isFolder: false,
    isTrashed: true,
    path: "/quarterly-report.pdf",
    sharedWith: [],
    tags: [],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    trashedAt: new Date().toISOString(),
    trashedBy: CURRENT_USER_ID,
    trashedByEmail: "otter@example.com",
    originalLocation: "Invoices",
    originalFolderMissing: false,
    versions: [],
    ...overrides,
  };
}

function currentUser(): User {
  return {
    id: CURRENT_USER_ID,
    email: "otter@example.com",
    displayName: "Otter",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}

function page(items: FileItem[]): PaginatedResponse<FileItem> {
  return { data: items, total: items.length, page: 1, pageSize: 50, hasMore: false };
}

function renderView() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <RecentlyDeletedContent />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: currentUser(), isAuthenticated: true, isLoading: false });
});

describe("Story 1 — Recently deleted view in the sidebar", () => {
  it("shows a Recently deleted entry in the System group", () => {
    render(
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>
    );
    const link = screen.getByRole("link", { name: "Recently deleted" });
    expect(link).toHaveAttribute("href", "/trash");
    expect(screen.getByText("System")).toBeInTheDocument();
  });

  it("lists deleted items and states the 30 day retention", async () => {
    vi.mocked(filesApi.getTrashed).mockResolvedValue(page([makeItem()]));
    renderView();

    expect(await screen.findByText("quarterly-report.pdf")).toBeInTheDocument();
    expect(
      screen.getByText(/After 30 days they are removed permanently/i)
    ).toBeInTheDocument();
  });

  it("shows an empty state when nothing was deleted in 30 days", async () => {
    vi.mocked(filesApi.getTrashed).mockResolvedValue(page([]));
    renderView();

    expect(
      await screen.findByText("Nothing deleted in the last 30 days")
    ).toBeInTheDocument();
    expect(screen.queryByText("quarterly-report.pdf")).not.toBeInTheDocument();
  });
});

describe("Story 2 — Deletion details on every row", () => {
  it("shows name, original location, deleted by and deleted at", async () => {
    vi.mocked(filesApi.getTrashed).mockResolvedValue(
      page([makeItem({ trashedBy: "someone-else", trashedByEmail: "ada@example.com" })])
    );
    renderView();

    expect(await screen.findByText("quarterly-report.pdf")).toBeInTheDocument();
    expect(screen.getByText(/In Invoices/)).toBeInTheDocument();
    expect(screen.getByText(/Deleted by ada@example.com/)).toBeInTheDocument();
    expect(screen.getByText(/ago|just now/i)).toBeInTheDocument();
  });

  it("labels the deleter as you for the signed-in user", () => {
    expect(
      deletedByLabel({ trashedBy: CURRENT_USER_ID, trashedByEmail: "otter@example.com" }, CURRENT_USER_ID)
    ).toBe("you");
    expect(deletedByLabel({ trashedBy: "other", trashedByEmail: undefined }, CURRENT_USER_ID)).toBe(
      "unknown"
    );
  });

  it("shows the deleted-folder location returned by the service", async () => {
    vi.mocked(filesApi.getTrashed).mockResolvedValue(
      page([
        makeItem({
          originalLocation: "My Files (original folder deleted)",
          originalFolderMissing: true,
        }),
      ])
    );
    renderView();

    expect(
      await screen.findByText(/In My Files \(original folder deleted\)/)
    ).toBeInTheDocument();
  });
});

describe("Story 3 — Restore to the original location", () => {
  it("restores an item and reports success", async () => {
    vi.mocked(filesApi.getTrashed)
      .mockResolvedValueOnce(page([makeItem()]))
      .mockResolvedValue(page([]));
    vi.mocked(filesApi.restore).mockResolvedValue(undefined);
    renderView();

    fireEvent.click(await screen.findByRole("button", { name: /Restore/ }));

    await waitFor(() =>
      expect(vi.mocked(filesApi.restore).mock.calls[0]?.[0]).toBe("file-1")
    );
    await waitFor(() =>
      expect(screen.queryByText("quarterly-report.pdf")).not.toBeInTheDocument()
    );
  });
});

describe("Story 4 — Restoring into a deleted parent lands the item in root", () => {
  it("flags items whose original folder is gone before restore", async () => {
    vi.mocked(filesApi.getTrashed).mockResolvedValue(
      page([
        makeItem({
          originalLocation: "My Files (original folder deleted)",
          originalFolderMissing: true,
        }),
      ])
    );
    renderView();

    expect(
      await screen.findByText(/Original folder was deleted .* restores to My Files/)
    ).toBeInTheDocument();
  });

  it("does not flag items whose original folder still exists", async () => {
    vi.mocked(filesApi.getTrashed).mockResolvedValue(page([makeItem()]));
    renderView();

    expect(await screen.findByText("quarterly-report.pdf")).toBeInTheDocument();
    expect(screen.queryByText(/restores to My Files/)).not.toBeInTheDocument();
  });
});

describe("page export", () => {
  it("exports the page component", () => {
    expect(TrashPageContent).toBeTypeOf("function");
  });
});
