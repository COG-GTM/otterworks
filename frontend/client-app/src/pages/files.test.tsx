import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FileItem } from "@/types";
import { useUIStore } from "@/stores/ui-store";
import { filesApi } from "@/lib/api";
import FilesPage from "./files";

vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/api", () => ({
  filesApi: { list: vi.fn(), listFolders: vi.fn(), getFolder: vi.fn() },
}));

function file(id: string, name: string, size: number, updatedAt: string): FileItem {
  return {
    id,
    name,
    mimeType: "text/plain",
    size,
    parentId: null,
    ownerId: "u1",
    ownerName: "Owner",
    isFolder: false,
    path: `/${name}`,
    sharedWith: [],
    tags: [],
    createdAt: updatedAt,
    updatedAt,
    versions: [],
  };
}

const FILES = [
  file("f1", "bravo.txt", 300, "2026-01-02T00:00:00Z"),
  file("f2", "alpha.txt", 100, "2026-01-03T00:00:00Z"),
  file("f3", "charlie.txt", 200, "2026-01-01T00:00:00Z"),
];

function mockListing(files: FileItem[], folders: FileItem[] = []) {
  vi.mocked(filesApi.list).mockResolvedValue({
    data: files,
    total: files.length,
    page: 1,
    pageSize: 50,
    hasMore: false,
  });
  vi.mocked(filesApi.listFolders).mockResolvedValue(folders);
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/files"]}>
        <FilesPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function renderedFileNames() {
  return screen.getAllByText(/^(alpha|bravo|charlie)\.txt$/).map((el) => el.textContent);
}

function sortIcon(label: string) {
  const header = screen.getByRole("button", { name: label });
  return header.querySelector("svg")?.getAttribute("class") ?? "";
}

describe("Files page", () => {
  beforeEach(() => {
    vi.mocked(filesApi.list).mockReset();
    vi.mocked(filesApi.listFolders).mockReset();
    useUIStore.setState({ viewMode: "grid", sortConfig: { field: "name", direction: "asc" } });
  });

  it.each([
    ["list", ".space-y-1 > .flex.items-center"],
    ["grid", ".grid > .rounded-xl"],
  ] as const)("shows the %s skeleton while loading", (viewMode, selector) => {
    useUIStore.setState({ viewMode });
    vi.mocked(filesApi.list).mockReturnValue(new Promise(() => {}));
    vi.mocked(filesApi.listFolders).mockReturnValue(new Promise(() => {}));
    const { container } = renderPage();
    expect(container.querySelectorAll(selector).length).toBeGreaterThan(0);
    expect(screen.queryByText("This folder is empty")).not.toBeInTheDocument();
  });

  it("shows the empty state when the folder has no items", async () => {
    mockListing([]);
    renderPage();
    expect(await screen.findByText("This folder is empty")).toBeInTheDocument();
    expect(screen.queryByText(/\.txt$/)).not.toBeInTheDocument();
  });

  it("renders folders and files once loaded", async () => {
    mockListing(FILES, [{ ...file("d1", "Reports", 0, "2026-01-01T00:00:00Z"), isFolder: true }]);
    renderPage();
    expect(await screen.findByText("Reports")).toBeInTheDocument();
    expect(renderedFileNames()).toEqual(["alpha.txt", "bravo.txt", "charlie.txt"]);
    expect(screen.queryByText("This folder is empty")).not.toBeInTheDocument();
  });

  it("toggles sort direction and icons in list view", async () => {
    useUIStore.setState({ viewMode: "list" });
    mockListing(FILES);
    renderPage();
    await screen.findByText("alpha.txt");

    expect(sortIcon("Name")).toContain("lucide-chevron-up");
    expect(sortIcon("Size")).toContain("lucide-arrow-up-down");
    expect(sortIcon("Size")).toContain("opacity-0");

    fireEvent.click(screen.getByRole("button", { name: "Name" }));
    expect(sortIcon("Name")).toContain("lucide-chevron-down");
    expect(renderedFileNames()).toEqual(["charlie.txt", "bravo.txt", "alpha.txt"]);

    fireEvent.click(screen.getByRole("button", { name: "Size" }));
    expect(sortIcon("Size")).toContain("lucide-chevron-up");
    expect(sortIcon("Name")).toContain("lucide-arrow-up-down");
    expect(renderedFileNames()).toEqual(["alpha.txt", "charlie.txt", "bravo.txt"]);
  });
});
