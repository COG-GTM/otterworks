import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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
  ownerName: "Otter",
  isFolder: true,
  path: "/Reports",
  sharedWith: [],
  tags: [],
  versions: [],
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

function renderCard(props: Partial<Parameters<typeof FolderCard>[0]> = {}) {
  return render(
    <MemoryRouter>
      <FolderCard folder={folder} {...props} />
    </MemoryRouter>
  );
}

describe.each(["grid", "list"] as const)("FolderCard (%s view)", (view) => {
  it("selects through a labelled, natively focusable checkbox", () => {
    const onSelect = vi.fn();
    renderCard({ view, selectionActive: true, onSelect });

    const checkbox = screen.getByRole("checkbox", { name: "Select Reports" });
    checkbox.focus();
    expect(checkbox).toHaveFocus();

    fireEvent.click(checkbox);
    expect(onSelect).toHaveBeenCalledWith("folder-1");
  });

  it("reflects the selected state", () => {
    renderCard({ view, selectionActive: true, selected: true });
    expect(screen.getByRole("checkbox", { name: "Select Reports" })).toBeChecked();
  });

  it("closes the actions menu with Escape", () => {
    renderCard({ view });
    const trigger = screen.getByRole("button", { name: "More actions for Reports" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: /rename/i })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: /rename/i })).not.toBeInTheDocument();
  });

  it("renames from the menu and submits with Enter", () => {
    const onRename = vi.fn();
    renderCard({ view, onRename });

    fireEvent.click(screen.getByRole("button", { name: "More actions for Reports" }));
    fireEvent.click(screen.getByRole("button", { name: /rename/i }));

    const input = screen.getByDisplayValue("Reports");
    expect(input).toHaveFocus();
    fireEvent.change(input, { target: { value: "Q3 Reports" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onRename).toHaveBeenCalledWith("folder-1", "Q3 Reports");
    expect(screen.queryByDisplayValue("Q3 Reports")).not.toBeInTheDocument();
  });
});
