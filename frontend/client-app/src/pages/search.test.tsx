import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { SearchResult } from "@/types";
import { SearchResults } from "./search";

const base = { path: "/", updatedAt: new Date().toISOString(), ownerName: "Otter" };

const results: SearchResult[] = [
  { ...base, id: "doc-1", type: "document", name: "Quarterly plan" },
  { ...base, id: "fold-1", type: "folder", name: "Designs" },
  { ...base, id: "file-1", type: "file", name: "logo.png" },
];

function renderResults(props: Partial<Parameters<typeof SearchResults>[0]>) {
  return render(
    <MemoryRouter>
      <SearchResults submittedQuery="" isLoading={false} results={[]} total={undefined} {...props} />
    </MemoryRouter>,
  );
}

describe("SearchResults", () => {
  it("shows the initial empty state without a query", () => {
    renderResults({ isLoading: true });
    expect(screen.getByText("Search OtterWorks")).toBeInTheDocument();
  });

  it("shows a loader while a query is in flight", () => {
    const { container } = renderResults({ submittedQuery: "plan", isLoading: true });
    expect(container.querySelector(".animate-spin")).not.toBeNull();
    expect(screen.queryByText("Search OtterWorks")).not.toBeInTheDocument();
    expect(screen.queryByText("No results found")).not.toBeInTheDocument();
  });

  it("shows no-results state for an empty result set", () => {
    renderResults({ submittedQuery: "nothing" });
    expect(screen.getByText("No results found")).toBeInTheDocument();
    expect(screen.getByText(/No results for "nothing"/)).toBeInTheDocument();
  });

  it("links and colors each result by type", () => {
    renderResults({ submittedQuery: "o", results, total: 7 });
    expect(screen.getByText(/7 results for/)).toBeInTheDocument();

    const expected = [
      ["Quarterly plan", "/documents/doc-1", "text-blue-600"],
      ["Designs", "/files?folder=fold-1", "text-amber-600"],
      ["logo.png", "/files/file-1", "text-otter-600"],
    ] as const;
    for (const [name, href, color] of expected) {
      const link = screen.getByText(name).closest("a");
      expect(link).toHaveAttribute("href", href);
      expect(link?.querySelector(`.${color}`)).not.toBeNull();
    }
  });

  it("uses singular wording for one result", () => {
    renderResults({ submittedQuery: "logo", results: [results[2]] });
    expect(screen.getByText(/1 result for/)).toBeInTheDocument();
  });
});
