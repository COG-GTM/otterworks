import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { FolderCard } from "./folder-card";
import type { FileItem } from "@/types";

const folder: FileItem = {
  id: "folder-1",
  name: "Reports",
  mimeType: "application/x-directory",
  size: 0,
  parentId: null,
  ownerId: "user-1",
  ownerName: "Owner",
  isFolder: true,
  path: "/Reports",
  sharedWith: [],
  tags: [],
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
  versions: [],
};

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname + location.search}</output>;
}

function renderCard(props: Partial<React.ComponentProps<typeof FolderCard>> = {}) {
  return render(
    <MemoryRouter initialEntries={["/files"]}>
      <Routes>
        <Route path="*" element={<><FolderCard folder={folder} {...props} /><LocationProbe /></>} />
      </Routes>
    </MemoryRouter>
  );
}

describe.each(["grid", "list"] as const)("FolderCard (%s view)", (view) => {
  it("closes the actions menu with Escape and returns focus to the trigger", () => {
    renderCard({ view });
    const trigger = screen.getByRole("button", { name: "Actions for Reports" });
    trigger.focus();
    fireEvent.click(trigger);

    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menuitem", { name: "Rename" })).toHaveFocus();

    fireEvent.keyDown(document.activeElement ?? document, { key: "Escape" });

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });

  it("still closes the actions menu when the backdrop is clicked", () => {
    const { container } = renderCard({ view });
    fireEvent.click(screen.getByRole("button", { name: "Actions for Reports" }));
    const backdrop = container.querySelector('[aria-hidden="true"].fixed');
    expect(backdrop).not.toBeNull();

    fireEvent.click(backdrop!);

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("runs menu actions from the keyboard-focusable menu items", () => {
    const onDelete = vi.fn();
    renderCard({ view, onDelete });
    fireEvent.click(screen.getByRole("button", { name: "Actions for Reports" }));

    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));

    expect(onDelete).toHaveBeenCalledWith("folder-1");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("does not open the folder when clicking around the rename input", () => {
    renderCard({ view });
    fireEvent.click(screen.getByRole("button", { name: "Actions for Reports" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    const input = screen.getByDisplayValue("Reports");

    fireEvent.click(input.parentElement!);
    fireEvent.click(input);

    expect(screen.getByTestId("location")).toHaveTextContent(/^\/files$/);
    expect(input).toBeInTheDocument();
  });

  it("opens the folder when the card is clicked outside rename mode", () => {
    renderCard({ view });

    fireEvent.click(screen.getByRole("link"));

    expect(screen.getByTestId("location")).toHaveTextContent("/files?folder=folder-1");
  });

  it("calls onSelect when the selection checkbox changes", () => {
    const onSelect = vi.fn();
    renderCard({ view, onSelect, selectionActive: true });
    const checkbox = screen.getByRole("checkbox", { name: "Select Reports" });

    fireEvent.click(checkbox);

    expect(onSelect).toHaveBeenCalledWith("folder-1");
  });
});
