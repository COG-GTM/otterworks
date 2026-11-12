import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PaginatedResponse, SearchResult } from "@/types";

const search = vi.fn<() => Promise<PaginatedResponse<SearchResult>>>();

vi.mock("@/lib/api", () => ({ searchApi: { search: () => search() } }));
vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

import SearchPage from "./search";

function result(type: SearchResult["type"], id: string): SearchResult {
  return {
    id,
    type,
    name: `${type} ${id}`,
    path: "/",
    updatedAt: new Date().toISOString(),
    ownerName: "Otter",
  };
}

function renderAt(url: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <SearchPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SearchPage", () => {
  beforeEach(() => search.mockReset());

  it("shows the idle empty state without a query", () => {
    renderAt("/search");
    expect(screen.getByText("Search OtterWorks")).toBeInTheDocument();
    expect(search).not.toHaveBeenCalled();
  });

  it("shows the loader while the search is pending", async () => {
    let finish: (value: PaginatedResponse<SearchResult>) => void = () => {};
    search.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    renderAt("/search?q=otter");
    expect(await screen.findByRole("status", { name: "Loading" })).toBeInTheDocument();
    expect(screen.queryByText("Search OtterWorks")).not.toBeInTheDocument();
    finish({ data: [], total: 0, page: 1, pageSize: 20, hasMore: false });
    expect(await screen.findByText("No results found")).toBeInTheDocument();
  });

  it("shows the no-results state when the search returns nothing", async () => {
    search.mockResolvedValue({ data: [], total: 0, page: 1, pageSize: 20, hasMore: false });
    renderAt("/search?q=nothing");
    expect(await screen.findByText("No results found")).toBeInTheDocument();
  });

  it("links and pluralises each result type", async () => {
    search.mockResolvedValue({
      data: [result("document", "d1"), result("folder", "f1"), result("file", "x1")],
      total: 3,
      page: 1,
      pageSize: 20,
      hasMore: false,
    });
    renderAt("/search?q=otter");
    expect(await screen.findByText(/3 results for/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /document d1/ })).toHaveAttribute("href", "/documents/d1");
    expect(screen.getByRole("link", { name: /folder f1/ })).toHaveAttribute("href", "/files?folder=f1");
    expect(screen.getByRole("link", { name: /file x1/ })).toHaveAttribute("href", "/files/x1");
  });

  it.each([
    ["document", "d1", "lucide-file-text", "text-blue-600 bg-blue-50"],
    ["folder", "f1", "lucide-folder-open", "text-amber-600 bg-amber-50"],
    ["file", "x1", "lucide-file", "text-otter-600 bg-otter-50"],
  ] as const)("renders the %s icon and colour", async (type, id, iconClass, colorClass) => {
    search.mockResolvedValue({ data: [result(type, id)], total: 1, page: 1, pageSize: 20, hasMore: false });
    renderAt("/search?q=otter");
    const link = await screen.findByRole("link", { name: new RegExp(`${type} ${id}`) });
    const icon = link.querySelector("svg");
    expect(icon).toHaveClass(iconClass);
    expect(icon?.parentElement).toHaveClass(colorClass);
  });

  it("uses the singular for a single result", async () => {
    search.mockResolvedValue({ data: [result("file", "x1")], total: 1, page: 1, pageSize: 20, hasMore: false });
    renderAt("/search?q=otter");
    expect(await screen.findByText(/1 result for/)).toBeInTheDocument();
  });
});
