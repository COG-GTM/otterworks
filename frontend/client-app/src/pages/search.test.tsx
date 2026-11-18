import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SearchResult } from "@/types";

const { searchMock } = vi.hoisted(() => ({ searchMock: vi.fn() }));

vi.mock("@/lib/api", () => ({ searchApi: { search: searchMock } }));
vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

import SearchPage from "./search";

const results: SearchResult[] = [
  {
    id: "doc-1",
    type: "document",
    name: "Quarterly report",
    path: "/Reports",
    updatedAt: "2026-01-01T00:00:00Z",
    ownerName: "Ada",
  },
  {
    id: "file-1",
    type: "file",
    name: "report.pdf",
    path: "/Reports",
    updatedAt: "2026-01-02T00:00:00Z",
    ownerName: "Ada",
  },
  {
    id: "file-2",
    type: "file",
    name: "report-draft.pdf",
    path: "/Drafts",
    updatedAt: "2026-01-03T00:00:00Z",
    ownerName: "Grace",
  },
];

function renderSearch() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/search?q=report"]}>
        <Routes>
          <Route path="/search" element={<SearchPage />} />
          <Route path="/documents/:id" element={<p>Document editor</p>} />
          <Route path="/files/:id" element={<p>File details</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function highlightedName() {
  const selected = screen
    .getAllByRole("option")
    .filter((option) => option.getAttribute("aria-selected") === "true");
  return selected.map((option) => option.querySelector("p")?.textContent);
}

describe("Search results keyboard navigation", () => {
  beforeEach(() => {
    searchMock.mockReset();
    searchMock.mockResolvedValue({
      data: results,
      total: results.length,
      page: 1,
      pageSize: 20,
      totalPages: 1,
    });
  });

  it("moves the highlight with the arrow keys and stops at the first and last result", async () => {
    renderSearch();
    const input = screen.getByRole("textbox", { name: "Search query" });
    await screen.findByText("Quarterly report");
    expect(highlightedName()).toEqual([]);

    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(highlightedName()).toEqual(["Quarterly report"]);
    expect(input).toHaveAttribute("aria-activedescendant", "search-result-doc-1");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(highlightedName()).toEqual(["report-draft.pdf"]);

    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(highlightedName()).toEqual(["report-draft.pdf"]);

    fireEvent.keyDown(input, { key: "ArrowUp" });
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(highlightedName()).toEqual(["Quarterly report"]);

    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(highlightedName()).toEqual(["Quarterly report"]);
  });

  it("opens the highlighted document in the editor with Enter", async () => {
    renderSearch();
    const input = screen.getByRole("textbox", { name: "Search query" });
    await screen.findByText("Quarterly report");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(await screen.findByText("Document editor")).toBeInTheDocument();
  });

  it("opens the highlighted file details with Enter", async () => {
    renderSearch();
    const input = screen.getByRole("textbox", { name: "Search query" });
    await screen.findByText("report.pdf");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(await screen.findByText("File details")).toBeInTheDocument();
  });

  it("resets the highlight when the query changes", async () => {
    renderSearch();
    const input = screen.getByRole("textbox", { name: "Search query" });
    await screen.findByText("Quarterly report");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(highlightedName()).toEqual(["report.pdf"]);

    fireEvent.change(input, { target: { value: "reports" } });
    await waitFor(() => expect(highlightedName()).toEqual([]));
    expect(input).not.toHaveAttribute("aria-activedescendant");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(highlightedName()).toEqual(["Quarterly report"]);
  });
});
