import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PaginatedResponse, SearchResult } from "@/types";

const search = vi.fn<(filters: unknown) => Promise<PaginatedResponse<SearchResult>>>();

vi.mock("@/lib/api", () => ({ searchApi: { search: (filters: unknown) => search(filters) } }));
vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

import SearchPage from "./search";

function renderAt(url: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <SearchPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function result(id: string, type: SearchResult["type"]): SearchResult {
  return { id, type, name: `${type}-${id}`, path: "/", updatedAt: new Date().toISOString(), ownerName: "Otter" };
}

function page(data: SearchResult[], total = data.length): PaginatedResponse<SearchResult> {
  return { data, total, page: 1, pageSize: 20, hasMore: false };
}

describe("Search page", () => {
  beforeEach(() => search.mockReset());

  it("shows the idle empty state without a query", () => {
    renderAt("/search");
    expect(screen.getByText("Search OtterWorks")).toBeInTheDocument();
    expect(search).not.toHaveBeenCalled();
  });

  it("shows the no-results state", async () => {
    search.mockResolvedValue(page([]));
    renderAt("/search?q=zzz");
    expect(await screen.findByText("No results found")).toBeInTheDocument();
    expect(screen.getByText('No results for "zzz". Try different keywords.')).toBeInTheDocument();
  });

  it("pluralises the result count and links each result type", async () => {
    search.mockResolvedValue(page([result("1", "document"), result("2", "folder"), result("3", "file")], 7));
    renderAt("/search?q=otter");
    expect(await screen.findByText(/7 results for/)).toBeInTheDocument();
    expect(screen.getByText("document-1").closest("a")).toHaveAttribute("href", "/documents/1");
    expect(screen.getByText("folder-2").closest("a")).toHaveAttribute("href", "/files?folder=2");
    expect(screen.getByText("file-3").closest("a")).toHaveAttribute("href", "/files/3");
  });

  it("uses the singular for exactly one result", async () => {
    search.mockResolvedValue(page([result("9", "file")]));
    renderAt("/search?q=one");
    expect(await screen.findByText(/^1 result for/)).toBeInTheDocument();
  });
});
