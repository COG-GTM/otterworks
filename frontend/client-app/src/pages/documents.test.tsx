import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Document } from "@/types";
import { documentsApi } from "@/lib/api";
import { useUIStore } from "@/stores/ui-store";
import DocumentsPage from "./documents";

vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/api", () => ({
  documentsApi: {
    list: vi.fn(),
    create: vi.fn(),
    delete: vi.fn(),
  },
  starredApi: {
    isStarred: () => false,
    toggle: () => false,
  },
}));

function doc(id: string, title: string): Document {
  return {
    id,
    title,
    content: "",
    ownerId: "u1",
    ownerName: "Otter",
    parentId: null,
    sharedWith: [],
    collaborators: [],
    tags: [],
    wordCount: 0,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
  };
}

function EditorStub() {
  const { id } = useParams();
  return <p>editor page {id}</p>;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/documents"]}>
        <Routes>
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/documents/:id" element={<EditorStub />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const list = vi.mocked(documentsApi.list);
const create = vi.mocked(documentsApi.create);

describe("DocumentsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUIStore.setState({ viewMode: "grid" });
  });

  it("lists documents from either the items or data envelope", async () => {
    list.mockResolvedValueOnce({ items: [doc("1", "Roadmap")] } as never);
    const { unmount } = renderPage();
    expect(await screen.findByText("Roadmap")).toBeInTheDocument();
    unmount();

    list.mockResolvedValueOnce({ data: [doc("2", "Budget")] } as never);
    renderPage();
    expect(await screen.findByText("Budget")).toBeInTheDocument();
  });

  it("filters by title case-insensitively and shows a no-match state", async () => {
    list.mockResolvedValue({ data: [doc("1", "Roadmap"), doc("2", "Budget")] } as never);
    renderPage();
    await screen.findByText("Roadmap");

    const filter = screen.getByPlaceholderText("Filter documents...");
    fireEvent.change(filter, { target: { value: "ROAD" } });
    expect(screen.getByText("Roadmap")).toBeInTheDocument();
    expect(screen.queryByText("Budget")).not.toBeInTheDocument();

    fireEvent.change(filter, { target: { value: "zzz" } });
    expect(screen.getByText("No matching documents")).toBeInTheDocument();
    expect(screen.getByText("Try a different search term")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create document" })).not.toBeInTheDocument();
  });

  it("offers to create the first document when the list is empty", async () => {
    list.mockResolvedValue({ data: [] } as never);
    create.mockResolvedValue(doc("new-42", "Untitled document"));
    renderPage();

    expect(await screen.findByText("No documents yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create document" }));

    await waitFor(() => expect(create).toHaveBeenCalledWith("Untitled document"));
    expect(await screen.findByText("editor page new-42")).toBeInTheDocument();
  });

  it("switches between grid and list layouts", async () => {
    list.mockResolvedValue({ data: [doc("1", "Roadmap")] } as never);
    renderPage();
    await screen.findByText("Roadmap");

    const [gridBtn, listBtn] = screen
      .getAllByRole("button")
      .filter((b) => b.className.includes("p-2 transition"));
    const listing = () => screen.getByText("Roadmap").closest(".grid, .space-y-1");
    expect(listing()).toHaveClass("grid");

    fireEvent.click(listBtn);
    expect(useUIStore.getState().viewMode).toBe("list");
    expect(listing()).toHaveClass("space-y-1");
    expect(listing()).not.toHaveClass("grid");
    expect(listing()?.firstElementChild).toHaveClass("flex", "items-center", "gap-4");

    fireEvent.click(gridBtn);
    expect(useUIStore.getState().viewMode).toBe("grid");
    expect(listing()).toHaveClass("grid");
  });
});
