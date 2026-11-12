import type { ReactNode } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FileItem } from "@/types";
import { useUIStore } from "@/stores/ui-store";

const { filesApi } = vi.hoisted(() => ({
  filesApi: {
    list: vi.fn(),
    listFolders: vi.fn(),
    getFolder: vi.fn(),
  },
}));

vi.mock("@/lib/api", () => ({ filesApi, starredApi: {} }));
vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

import FilesPage from "./files";

function file(overrides: Partial<FileItem>): FileItem {
  return {
    id: "f1",
    name: "report.pdf",
    mimeType: "application/pdf",
    size: 1024,
    parentId: null,
    ownerId: "u1",
    ownerName: "Otter",
    isFolder: false,
    path: "/report.pdf",
    sharedWith: [],
    tags: [],
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-02T00:00:00Z",
    versions: [],
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <FilesPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function listResponse(files: FileItem[]) {
  return { data: files, total: files.length, page: 1, pageSize: 50, hasMore: false };
}

describe("Files page listing", () => {
  beforeEach(() => {
    useUIStore.setState({ viewMode: "list", sortConfig: { field: "updatedAt", direction: "desc" } });
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it("shows the list skeleton while loading, then the empty state", async () => {
    let resolveFiles!: (value: ReturnType<typeof listResponse>) => void;
    filesApi.list.mockReturnValue(new Promise((resolve) => (resolveFiles = resolve)));
    filesApi.listFolders.mockResolvedValue([]);

    const { container } = renderPage();
    expect(container.querySelector(".space-y-1 .animate-pulse")).not.toBeNull();
    expect(container.querySelector(".grid .animate-pulse")).toBeNull();
    expect(screen.queryByText("This folder is empty")).not.toBeInTheDocument();

    await act(async () => resolveFiles(listResponse([])));
    expect(await screen.findByText("This folder is empty")).toBeInTheDocument();
    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(0);
    expect(screen.queryByText("Name")).not.toBeInTheDocument();
  });

  it("renders folders and files once loaded and swaps the sort icon on toggle", async () => {
    filesApi.list.mockResolvedValue(listResponse([file({ id: "f1", name: "report.pdf" })]));
    filesApi.listFolders.mockResolvedValue([
      file({ id: "d1", name: "Designs", isFolder: true, mimeType: "folder" }),
    ]);

    renderPage();
    expect(await screen.findByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByText("Designs")).toBeInTheDocument();
    expect(screen.queryByText("This folder is empty")).not.toBeInTheDocument();

    const nameHeader = screen.getByRole("button", { name: "Name" });
    expect(nameHeader.querySelector(".lucide-arrow-up-down")).not.toBeNull();

    fireEvent.click(nameHeader);
    expect(useUIStore.getState().sortConfig).toEqual({ field: "name", direction: "asc" });
    expect(nameHeader.querySelector(".lucide-chevron-up")).not.toBeNull();

    fireEvent.click(nameHeader);
    expect(useUIStore.getState().sortConfig).toEqual({ field: "name", direction: "desc" });
    expect(nameHeader.querySelector(".lucide-chevron-down")).not.toBeNull();
  });

  it("uses the grid skeleton while loading in grid view", () => {
    useUIStore.setState({ viewMode: "grid" });
    filesApi.list.mockReturnValue(new Promise(() => {}));
    filesApi.listFolders.mockReturnValue(new Promise(() => {}));

    const { container } = renderPage();
    expect(container.querySelector(".grid .animate-pulse")).not.toBeNull();
    expect(container.querySelector(".space-y-1 .animate-pulse")).toBeNull();
  });
});
