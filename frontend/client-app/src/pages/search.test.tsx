import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { SearchResultRow } from "./search";
import type { SearchResult } from "@/types";

function renderRow(type: SearchResult["type"]) {
  const result: SearchResult = {
    id: "abc123",
    type,
    name: `My ${type}`,
    path: "/",
    updatedAt: new Date().toISOString(),
    ownerName: "Otter",
  };
  render(
    <MemoryRouter>
      <SearchResultRow result={result} />
    </MemoryRouter>,
  );
  const link = screen.getByRole("link", { name: new RegExp(`My ${type}`) });
  const iconWrapper = link.firstElementChild as HTMLElement;
  const icon = iconWrapper.querySelector("svg") as SVGElement;
  return { link, iconWrapper, icon };
}

describe("SearchResultRow", () => {
  it.each([
    ["document", "/documents/abc123", "text-blue-600 bg-blue-50", "lucide-file-text"],
    ["folder", "/files?folder=abc123", "text-amber-600 bg-amber-50", "lucide-folder-open"],
    ["file", "/files/abc123", "text-otter-600 bg-otter-50", "lucide-file"],
  ] as const)("renders a %s result with its link, colors and icon", (type, href, colors, iconClass) => {
    const { link, iconWrapper, icon } = renderRow(type);
    expect(link).toHaveAttribute("href", href);
    for (const cls of colors.split(" ")) expect(iconWrapper).toHaveClass(cls);
    expect(icon).toHaveClass(iconClass);
  });
});
