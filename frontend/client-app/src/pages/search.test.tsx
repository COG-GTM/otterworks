import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { searchApi } from "@/lib/api";
import type { PaginatedResponse, SearchResult } from "@/types";
import SearchPage from "./search";

vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/api", () => ({
  searchApi: { search: vi.fn() },
}));

const search = vi.mocked(searchApi.search);

function result(type: SearchResult["type"], id: string, name: string): SearchResult {
  return {
    id,
    name,
    type,
    path: "/",
    ownerName: "Owner",
    updatedAt: new Date().toISOString(),
  } as SearchResult;
}

function page(data: SearchResult[], total = data.length): PaginatedResponse<SearchResult> {
  return { data, total } as PaginatedResponse<SearchResult>;
}

function renderSearch(url = "/search") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <SearchPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SearchPage results", () => {
  beforeEach(() => {
    search.mockReset();
  });

  it("shows the initial empty state without querying", () => {
    renderSearch();
    expect(screen.getByText("Search OtterWorks")).toBeInTheDocument();
    expect(search).not.toHaveBeenCalled();
  });

  it("shows a loader while the query is in flight", () => {
    search.mockReturnValue(new Promise(() => {}));
    const { container } = renderSearch("/search?q=report");
    expect(container.querySelector(".animate-spin")).not.toBeNull();
    expect(screen.queryByText("No results found")).toBeNull();
  });

  it("shows the no-results state for an empty response", async () => {
    search.mockResolvedValue(page([]));
    renderSearch("/search?q=zzz");
    expect(await screen.findByText("No results found")).toBeInTheDocument();
    expect(screen.getByText('No results for "zzz". Try different keywords.')).toBeInTheDocument();
  });

  it("links each result type to its own route", async () => {
    search.mockResolvedValue(
      page([
        result("document", "d1", "Doc One"),
        result("folder", "f1", "Folder One"),
        result("file", "x1", "File One"),
      ]),
    );
    renderSearch("/search?q=one");
    expect(await screen.findByText(/3 results for/)).toBeInTheDocument();
    const link = (name: string) => screen.getByText(name).closest("a");
    expect(link("Doc One")).toHaveAttribute("href", "/documents/d1");
    expect(link("Folder One")).toHaveAttribute("href", "/files?folder=f1");
    expect(link("File One")).toHaveAttribute("href", "/files/x1");
    expect(link("Doc One")?.firstElementChild).toHaveClass("text-blue-600", "bg-blue-50");
    expect(link("Folder One")?.firstElementChild).toHaveClass("text-amber-600", "bg-amber-50");
    expect(link("File One")?.firstElementChild).toHaveClass("text-otter-600", "bg-otter-50");
    const icon = (name: string) => link(name)?.querySelector("svg");
    expect(icon("Doc One")).toHaveClass("lucide-file-text");
    expect(icon("Folder One")).toHaveClass("lucide-folder-open");
    expect(icon("File One")).toHaveClass("lucide-file");
  });

  it("reports the server total rather than the page size", async () => {
    search.mockResolvedValue(
      page([result("file", "x1", "Page One"), result("file", "x2", "Page Two")], 42),
    );
    renderSearch("/search?q=page");
    expect(await screen.findByText(/42 results for/)).toBeInTheDocument();
  });

  it("uses the singular label for a single result", async () => {
    search.mockResolvedValue(page([result("file", "x1", "Only File")]));
    renderSearch("/search?q=only");
    expect(await screen.findByText(/1 result for/)).toBeInTheDocument();
  });
});
