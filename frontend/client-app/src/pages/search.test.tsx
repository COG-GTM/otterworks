import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SearchResult } from "@/types";

const search = vi.fn();

vi.mock("@/lib/api", () => ({
  searchApi: { search: (...args: unknown[]) => search(...args) },
}));

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

function renderPage(url: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <SearchPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function rowFor(name: string) {
  const link = screen.getByText(name).closest("a");
  expect(link).not.toBeNull();
  return link as HTMLAnchorElement;
}

describe("SearchPage", () => {
  beforeEach(() => {
    search.mockReset();
  });

  it("shows the start state before a query is submitted", () => {
    renderPage("/search");
    expect(screen.getByText("Search OtterWorks")).toBeInTheDocument();
    expect(search).not.toHaveBeenCalled();
  });

  it("shows the loader while the search request is pending", async () => {
    search.mockReturnValue(new Promise(() => {}));
    const { container } = renderPage("/search?q=pending");
    await vi.waitFor(() => expect(search).toHaveBeenCalled());
    expect(container.querySelector(".animate-spin")).not.toBeNull();
    expect(screen.queryByText("No results found")).not.toBeInTheDocument();
    expect(screen.queryByText("Search OtterWorks")).not.toBeInTheDocument();
  });

  it("shows the no-results state for an empty result set", async () => {
    search.mockResolvedValue({ data: [], total: 0 });
    renderPage("/search?q=zzz");
    expect(await screen.findByText("No results found")).toBeInTheDocument();
    expect(screen.getByText('No results for "zzz". Try different keywords.')).toBeInTheDocument();
  });

  it("links and styles each result by type", async () => {
    search.mockResolvedValue({
      data: [
        result({ id: "d1", type: "document", name: "Doc" }),
        result({ id: "f1", type: "folder", name: "Folder" }),
        result({ id: "x1", type: "file", name: "File" }),
        result({ id: "u1", type: "mystery" as SearchResult["type"], name: "Unknown" }),
        result({ id: "c1", type: "constructor" as SearchResult["type"], name: "Inherited" }),
      ],
      total: 5,
    });
    renderPage("/search?q=otter");

    expect(await screen.findByText(/5 results for/)).toBeInTheDocument();

    const cases: Array<[string, string, string, string]> = [
      ["Doc", "/documents/d1", "text-blue-600", "lucide-file-text"],
      ["Folder", "/files?folder=f1", "text-amber-600", "lucide-folder-open"],
      ["File", "/files/x1", "text-otter-600", "lucide-file"],
      ["Unknown", "/files/u1", "text-otter-600", "lucide-file"],
      ["Inherited", "/files/c1", "text-otter-600", "lucide-file"],
    ];
    for (const [name, href, color, icon] of cases) {
      const row = rowFor(name);
      expect(row).toHaveAttribute("href", href);
      const iconBox = row.firstElementChild as HTMLElement;
      expect(iconBox).toHaveClass(color);
      expect(iconBox.querySelector("svg")).toHaveClass(icon);
    }
  });

  it("uses the singular label for a single result", async () => {
    search.mockResolvedValue({ data: [result({ id: "one", name: "Only" })], total: 1 });
    renderPage("/search?q=only");
    expect(await screen.findByText(/^1 result for/)).toBeInTheDocument();
  });
});
