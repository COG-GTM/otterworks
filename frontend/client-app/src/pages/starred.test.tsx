import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Document, FileItem } from "@/types";
import { useAuthStore } from "@/stores/auth-store";
import { useUIStore } from "@/stores/ui-store";
import StarredPage from "./starred";

vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

const fileRecords: Record<string, FileItem> = {};
const docRecords: Record<string, Document> = {};

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    filesApi: {
      ...actual.filesApi,
      get: vi.fn(async (id: string) => fileRecords[id]),
      getFolder: vi.fn(async (id: string) => fileRecords[id]),
    },
    documentsApi: {
      ...actual.documentsApi,
      get: vi.fn(async (id: string) => docRecords[id]),
    },
  };
});

function file(id: string, name: string, updatedAt: string, isFolder = false): FileItem {
  return {
    id,
    name,
    mimeType: isFolder ? "inode/directory" : "text/plain",
    size: 10,
    parentId: null,
    ownerId: "u1",
    ownerName: "User",
    isFolder,
    path: `/${name}`,
    sharedWith: [],
    tags: [],
    createdAt: updatedAt,
    updatedAt,
    versions: [],
  };
}

function doc(id: string, title: string, updatedAt: string): Document {
  return {
    id,
    title,
    content: "",
    ownerId: "u1",
    ownerName: "User",
    parentId: null,
    sharedWith: [],
    collaborators: [],
    tags: [],
    wordCount: 0,
    createdAt: updatedAt,
    updatedAt,
  };
}

function star(itemId: string, itemType: "file" | "folder" | "document") {
  const raw = localStorage.getItem("otter_starred_items");
  const map = raw ? JSON.parse(raw) : {};
  map[`u1:${itemId}`] = { itemId, itemType, starredAt: "2026-01-01T00:00:00Z" };
  localStorage.setItem("otter_starred_items", JSON.stringify(map));
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <StarredPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function fileSectionNames() {
  const heading = screen.getByRole("heading", { level: 2, name: /files|folders/i });
  const section = heading.closest("section") as HTMLElement;
  return within(section)
    .getAllByText(/\.(txt|pdf)$|^(Projects|archive)$/)
    .map((el) => el.textContent);
}

describe("Starred page sort and filter", () => {
  beforeEach(() => {
    localStorage.clear();
    useAuthStore.setState({
      user: { id: "u1", email: "u1@example.com", displayName: "User" } as never,
      isAuthenticated: true,
      isLoading: false,
    });
    useUIStore.setState({ viewMode: "list" });
    Object.assign(fileRecords, {
      f1: file("f1", "budget.txt", "2026-03-01T00:00:00Z"),
      f2: file("f2", "Agenda.pdf", "2026-05-01T00:00:00Z"),
      d1: file("d1", "Projects", "2026-04-01T00:00:00Z", true),
    });
    Object.assign(docRecords, { doc1: doc("doc1", "Roadmap", "2026-01-15T00:00:00Z") });
    star("f1", "file");
    star("f2", "file");
    star("d1", "folder");
    star("doc1", "document");
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("sorts by last modified by default and by name when chosen", async () => {
    renderPage();
    expect(await screen.findByText("Agenda.pdf")).toBeInTheDocument();
    expect(await screen.findByText("Projects")).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveValue("modified");
    expect(fileSectionNames()).toEqual(["Agenda.pdf", "Projects", "budget.txt"]);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "name" } });
    expect(fileSectionNames()).toEqual(["Agenda.pdf", "budget.txt", "Projects"]);
  });

  it("filters by type and shows a filter-specific empty state", async () => {
    renderPage();
    expect(await screen.findByText("Roadmap")).toBeInTheDocument();
    expect(await screen.findByText("Projects")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Folders" }));
    expect(screen.getByRole("button", { name: "Folders" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Projects")).toBeInTheDocument();
    expect(screen.queryByText("Agenda.pdf")).not.toBeInTheDocument();
    expect(screen.queryByText("Roadmap")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Documents" }));
    expect(screen.getByText("Roadmap")).toBeInTheDocument();
    expect(screen.queryByText("Projects")).not.toBeInTheDocument();
  });

  it("shows 'No starred folders' when no folders are starred", async () => {
    localStorage.clear();
    star("f1", "file");
    renderPage();
    expect(await screen.findByText("budget.txt")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Folders" }));
    expect(screen.getByText("No starred folders")).toBeInTheDocument();
  });
});
