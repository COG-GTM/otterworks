import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { SearchBar } from "./search-bar";

function renderSearchBar() {
  return render(
    <MemoryRouter>
      <input aria-label="Other input" />
      <textarea aria-label="Notes" />
      <div contentEditable data-testid="editor" />
      <SearchBar />
    </MemoryRouter>
  );
}

const searchInput = () => screen.getByRole("textbox", { name: "Search" });

describe("SearchBar", () => {
  it("hints at the / shortcut in the placeholder", () => {
    renderSearchBar();
    expect(searchInput()).toHaveAttribute(
      "placeholder",
      "Search files, documents... (press /)"
    );
  });

  it("focuses the search bar when / is pressed outside a text field", () => {
    renderSearchBar();
    expect(searchInput()).not.toHaveFocus();

    const notPrevented = fireEvent.keyDown(document.body, { key: "/" });

    expect(searchInput()).toHaveFocus();
    expect(notPrevented).toBe(false);
  });

  it("ignores / while typing in an input", () => {
    renderSearchBar();
    const other = screen.getByRole("textbox", { name: "Other input" });
    other.focus();

    const notPrevented = fireEvent.keyDown(other, { key: "/" });

    expect(other).toHaveFocus();
    expect(searchInput()).not.toHaveFocus();
    expect(notPrevented).toBe(true);
  });

  it("ignores / while typing in a textarea or the document editor", () => {
    renderSearchBar();
    const notes = screen.getByRole("textbox", { name: "Notes" });
    notes.focus();
    fireEvent.keyDown(notes, { key: "/" });
    expect(notes).toHaveFocus();

    fireEvent.keyDown(screen.getByTestId("editor"), { key: "/" });
    expect(searchInput()).not.toHaveFocus();
  });

  it("clears and blurs the search bar on Escape", () => {
    renderSearchBar();
    fireEvent.keyDown(document.body, { key: "/" });
    fireEvent.change(searchInput(), { target: { value: "quarterly report" } });
    expect(searchInput()).toHaveValue("quarterly report");

    fireEvent.keyDown(searchInput(), { key: "Escape" });

    expect(searchInput()).toHaveValue("");
    expect(searchInput()).not.toHaveFocus();
  });
});
