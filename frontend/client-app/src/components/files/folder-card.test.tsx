import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { FileItem } from "@/types";
import { FolderCard } from "./folder-card";

const folder: FileItem = {
  id: "folder-1",
  name: "Reports",
  mimeType: "application/x-directory",
  size: 0,
  parentId: null,
  ownerId: "user-1",
  ownerName: "User",
  isFolder: true,
  path: "/Reports",
  sharedWith: [],
  tags: [],
  versions: [],
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

function renderCard(props: Partial<Parameters<typeof FolderCard>[0]> = {}) {
  return render(
    <MemoryRouter initialEntries={["/start"]}>
      <Routes>
        <Route path="*" element={<LocationProbe />} />
      </Routes>
      <FolderCard folder={folder} {...props} />
    </MemoryRouter>
  );
}

describe.each(["grid", "list"] as const)("FolderCard (%s view)", (view) => {
  it("selects the folder through a native, labelled checkbox", () => {
    const onSelect = vi.fn();
    renderCard({ view, selectionActive: true, onSelect });

    const checkbox = screen.getByRole("checkbox", { name: "Select Reports" });
    expect(checkbox).not.toBeChecked();
    fireEvent.click(checkbox);

    expect(onSelect).toHaveBeenCalledWith("folder-1");
    expect(screen.getByTestId("location")).toHaveTextContent("/start");
  });

  it("is a focusable native control that reflects and toggles selection", () => {
    const onSelect = vi.fn();
    renderCard({ view, selectionActive: true, onSelect, selected: true });

    const checkbox = screen.getByRole("checkbox", { name: "Select Reports" });
    expect(checkbox).toBeChecked();
    checkbox.focus();
    expect(checkbox).toHaveFocus();
    fireEvent.click(checkbox);

    expect(onSelect).toHaveBeenCalledWith("folder-1");
  });

  it("closes the actions menu via the backdrop without navigating", () => {
    renderCard({ view });

    const trigger = screen.getByRole("button", { name: "Actions for Reports" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Rename" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close menu" }));

    expect(screen.queryByRole("button", { name: "Rename" })).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByTestId("location")).toHaveTextContent("/start");
  });

  it("renames without navigating when the rename input is clicked", () => {
    const onRename = vi.fn();
    renderCard({ view, onRename });

    fireEvent.click(screen.getByRole("button", { name: "Actions for Reports" }));
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));

    const input = screen.getByDisplayValue("Reports");
    fireEvent.click(input);
    fireEvent.change(input, { target: { value: "Q3 Reports" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onRename).toHaveBeenCalledWith("folder-1", "Q3 Reports");
    expect(screen.getByTestId("location")).toHaveTextContent("/start");
  });

  it("does not render interactive handlers on non-interactive elements", () => {
    const { container } = renderCard({ view, selectionActive: true, onSelect: vi.fn() });
    fireEvent.click(screen.getByRole("button", { name: "Actions for Reports" }));

    const card = container.querySelectorAll("div, span, p");
    card.forEach((el) => {
      const props = Object.entries(el).find(([k]) => k.startsWith("__reactProps"))?.[1] as
        | Record<string, unknown>
        | undefined;
      expect(props?.onClick, el.className).toBeUndefined();
    });
  });
});
