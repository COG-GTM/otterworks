import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { SearchBar } from "./search-bar";

function renderSearchBar() {
  render(
    <MemoryRouter>
      <SearchBar />
    </MemoryRouter>
  );
  return screen.getByRole("textbox", { name: "Search" }) as HTMLInputElement;
}

describe("SearchBar", () => {
  it("clears the text and removes focus when Esc is pressed", () => {
    const input = renderSearchBar();
    input.focus();
    fireEvent.change(input, { target: { value: "quarterly report" } });
    expect(input).toHaveValue("quarterly report");
    expect(input).toHaveFocus();

    fireEvent.keyDown(input, { key: "Escape" });

    expect(input).toHaveValue("");
    expect(input).not.toHaveFocus();
    expect(
      screen.queryByRole("button", { name: "Clear search" })
    ).not.toBeInTheDocument();
  });

  it("only removes focus when Esc is pressed on an empty search bar", () => {
    const input = renderSearchBar();
    input.focus();
    expect(input).toHaveFocus();

    fireEvent.keyDown(input, { key: "Escape" });

    expect(input).toHaveValue("");
    expect(input).not.toHaveFocus();
  });

  it("keeps clearing the text with the X button", () => {
    const input = renderSearchBar();
    fireEvent.change(input, { target: { value: "notes" } });

    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));

    expect(input).toHaveValue("");
  });
});
