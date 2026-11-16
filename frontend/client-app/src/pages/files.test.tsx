import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import type { FileItem } from "@/types";
import { useUIStore } from "@/stores/ui-store";

vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

function makeItem(id: string, name: string, mimeType: string, isFolder = false): FileItem {
  return {
    id,
    name,
    mimeType,
    size: 1024,
    parentId: null,
    ownerId: "u1",
    ownerName: "Owner",
    isFolder,
    path: `/${name}`,
    sharedWith: [],
    tags: [],
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    versions: [],
  };
}

const mockFiles = [
  makeItem("f1", "photo.png", "image/png"),
  makeItem("f2", "report.pdf", "application/pdf"),
  makeItem("f3", "notes.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
];
const mockFolders = [makeItem("d1", "Projects", "inode/directory", true)];

vi.mock("@/lib/api", () => ({
  filesApi: {
    list: vi.fn(async () => ({ data: mockFiles })),
    listFolders: vi.fn(async () => mockFolders),
    getFolder: vi.fn(),
  },
  starredApi: { isStarred: () => false, toggle: () => false },
}));

import FilesPage from "./files";

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <FilesPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function filterButton(label: string) {
  return within(screen.getByRole("group", { name: "Filter by file type" })).getByRole("button", {
    name: label,
  });
}

describe.each(["grid", "list"] as const)("My Files type filter (%s view)", (viewMode) => {
  beforeEach(() => {
    useUIStore.setState({ viewMode });
  });

  it("filters files by type while keeping folders visible", async () => {
    renderPage();
    expect(await screen.findByText("photo.png")).toBeInTheDocument();
    expect(filterButton("All")).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(filterButton("PDFs"));
    expect(filterButton("PDFs")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.queryByText("photo.png")).not.toBeInTheDocument();
    expect(screen.queryByText("notes.docx")).not.toBeInTheDocument();
    expect(screen.getByText("Projects")).toBeInTheDocument();

    fireEvent.click(filterButton("Documents"));
    expect(screen.getByText("notes.docx")).toBeInTheDocument();
    expect(screen.queryByText("report.pdf")).not.toBeInTheDocument();
  });

  it("shows an empty state with a Clear filter action when nothing matches", async () => {
    renderPage();
    await screen.findByText("photo.png");

    fireEvent.click(filterButton("Other"));
    expect(screen.getByText('No files match "Other"')).toBeInTheDocument();
    expect(screen.getByText("Projects")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear filter" }));
    expect(filterButton("All")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("photo.png")).toBeInTheDocument();
    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByText("notes.docx")).toBeInTheDocument();
  });
});
