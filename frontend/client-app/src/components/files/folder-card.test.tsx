import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { FolderCard } from "./folder-card";
import type { FileItem } from "@/types";

const folder = {
  id: "folder-1",
  name: "Reports",
  type: "folder",
  updatedAt: new Date().toISOString(),
} as unknown as FileItem;

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

function renderCard(props: Partial<React.ComponentProps<typeof FolderCard>> = {}) {
  return render(
    <MemoryRouter initialEntries={["/home"]}>
      <Routes>
        <Route path="*" element={<><FolderCard folder={folder} {...props} /><LocationProbe /></>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe.each(["grid", "list"] as const)("FolderCard (%s view)", (view) => {
  it("uses a labelled native checkbox for selection without navigating", () => {
    const onSelect = vi.fn();
    renderCard({ view, selectionActive: true, onSelect });
    const checkbox = screen.getByRole("checkbox", { name: "Select folder Reports" });
    fireEvent.click(checkbox);
    expect(onSelect).toHaveBeenCalledWith("folder-1");
    expect(screen.getByTestId("location")).toHaveTextContent("/home");
  });

  it("toggles selection from the keyboard via the native checkbox", () => {
    const onSelect = vi.fn();
    renderCard({ view, selectionActive: true, onSelect, selected: true });
    const checkbox = screen.getByRole("checkbox", { name: "Select folder Reports" });
    expect(checkbox).toBeChecked();
    checkbox.focus();
    expect(checkbox).toHaveFocus();
    fireEvent.click(checkbox);
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("closes the actions menu via a native button backdrop", () => {
    renderCard({ view });
    const trigger = screen.getByRole("button", { name: "Actions for folder Reports" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Rename" })).toBeInTheDocument();
    const backdrop = screen.getByRole("button", { name: "Close menu" });
    expect(backdrop).toHaveAttribute("tabindex", "-1");
    fireEvent.click(backdrop);
    expect(screen.queryByRole("button", { name: "Rename" })).not.toBeInTheDocument();
  });

  it("renames without navigating when the rename input is clicked", () => {
    const onRename = vi.fn();
    renderCard({ view, onRename });
    fireEvent.click(screen.getByRole("button", { name: "Actions for folder Reports" }));
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    const input = screen.getByDisplayValue("Reports");
    fireEvent.click(input);
    expect(screen.getByTestId("location")).toHaveTextContent("/home");
    fireEvent.change(input, { target: { value: "Q3 Reports" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onRename).toHaveBeenCalledWith("folder-1", "Q3 Reports");
  });

  it("still navigates into the folder from its link", () => {
    renderCard({ view });
    fireEvent.click(screen.getByRole("link"));
    expect(screen.getByTestId("location")).toHaveTextContent("/files?folder=folder-1");
  });
});
