import type { ReactNode } from "react";
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SearchResult } from "@/types";

const search = vi.fn();

vi.mock("@/lib/api", () => ({ searchApi: { search: (...args: unknown[]) => search(...args) } }));
vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

import SearchPage from "./search";

function result(overrides: Partial<SearchResult>): SearchResult {
  return {
    id: "id",
    type: "file",
    name: "name",
    path: "/",
    updatedAt: new Date().toISOString(),
    ownerName: "Otter",
    ...overrides,
  };
}

function renderPage(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <SearchPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("Search page", () => {
  beforeEach(() => search.mockReset());

  it("shows the landing state without a query", () => {
    renderPage("/search");
    expect(screen.getByText("Search OtterWorks")).toBeInTheDocument();
    expect(search).not.toHaveBeenCalled();
  });

  it("shows the empty state when nothing matches", async () => {
    search.mockResolvedValue({ data: [], total: 0 });
    renderPage("/search?q=nothing");
    expect(await screen.findByText("No results found")).toBeInTheDocument();
    expect(screen.getByText(/No results for "nothing"/)).toBeInTheDocument();
  });

  it("links and styles each result by type", async () => {
    search.mockResolvedValue({
      data: [
        result({ id: "d1", type: "document", name: "Doc" }),
        result({ id: "f1", type: "folder", name: "Folder" }),
        result({ id: "x1", type: "file", name: "File" }),
      ],
      total: 3,
    });
    renderPage("/search?q=otter");

    expect(await screen.findByText(/3 results for/)).toBeInTheDocument();
    const link = (name: string) => screen.getByText(name).closest("a")!;
    expect(link("Doc")).toHaveAttribute("href", "/documents/d1");
    expect(link("Folder")).toHaveAttribute("href", "/files?folder=f1");
    expect(link("File")).toHaveAttribute("href", "/files/x1");
    expect(link("Doc").firstElementChild).toHaveClass("text-blue-600", "bg-blue-50");
    expect(link("Folder").firstElementChild).toHaveClass("text-amber-600", "bg-amber-50");
    expect(link("File").firstElementChild).toHaveClass("text-otter-600", "bg-otter-50");
    expect(within(link("Doc")).getByText("Doc")).toBeInTheDocument();
  });

  it("uses the singular label for one result", async () => {
    search.mockResolvedValue({ data: [result({ id: "x1", name: "Only" })], total: 1 });
    renderPage("/search?q=only");
    expect(await screen.findByText(/^1 result for/)).toBeInTheDocument();
  });
});
