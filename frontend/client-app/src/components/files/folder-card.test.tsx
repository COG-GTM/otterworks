import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
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
  return <span data-testid="location">{location.pathname + location.search}</span>;
}

function expectStillOnFiles() {
  expect(screen.getByTestId("location").textContent).toBe("/files");
}

function renderCard(
  props: Partial<React.ComponentProps<typeof FolderCard>> = {},
  onOutsideClick: () => void = () => {}
) {
  return render(
    <MemoryRouter initialEntries={["/files"]}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              <FolderCard folder={folder} {...props} />
              <button type="button" onClick={onOutsideClick}>
                Outside
              </button>
              <LocationProbe />
            </>
          }
        />
      </Routes>
    </MemoryRouter>
  );
}

describe.each(["grid", "list"] as const)("FolderCard (%s view)", (view) => {
  it("opens an accessible action menu from the labelled trigger", () => {
    renderCard({ view });
    const trigger = screen.getByRole("button", { name: "More actions for Reports" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu", { name: "Actions for Reports" })).toBeInTheDocument();
    expect(screen.getAllByRole("menuitem").map((el) => el.textContent)).toEqual([
      "Rename",
      "Share",
      "Delete",
    ]);
    expectStillOnFiles();
  });

  it("closes the menu on Escape", () => {
    renderCard({ view });
    fireEvent.click(screen.getByRole("button", { name: "More actions for Reports" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("returns focus to the trigger when Escape is pressed inside the menu", () => {
    renderCard({ view });
    const trigger = screen.getByRole("button", { name: "More actions for Reports" });
    fireEvent.click(trigger);
    const share = screen.getByRole("menuitem", { name: "Share" });
    share.focus();
    fireEvent.keyDown(share, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("closes the menu on an outside press and still activates the outside target", () => {
    const onOutsideClick = vi.fn();
    renderCard({ view }, onOutsideClick);
    fireEvent.click(screen.getByRole("button", { name: "More actions for Reports" }));
    const outside = screen.getByRole("button", { name: "Outside" });
    fireEvent.pointerDown(outside);
    fireEvent.click(outside);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(onOutsideClick).toHaveBeenCalledTimes(1);
    expectStillOnFiles();
  });

  it("keeps the menu open when pressing inside it and runs the action", () => {
    const onDelete = vi.fn();
    renderCard({ view, onDelete });
    fireEvent.click(screen.getByRole("button", { name: "More actions for Reports" }));
    const del = screen.getByRole("menuitem", { name: "Delete" });
    fireEvent.pointerDown(del);
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.click(del);
    expect(onDelete).toHaveBeenCalledWith("folder-1");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expectStillOnFiles();
  });

  it("toggles selection through the native checkbox", () => {
    const onSelect = vi.fn();
    renderCard({ view, onSelect, selectionActive: true });
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Reports" }));
    expect(onSelect).toHaveBeenCalledWith("folder-1");
    expectStillOnFiles();
  });

  it("does not navigate when clicking the rename input", () => {
    renderCard({ view });
    fireEvent.click(screen.getByRole("button", { name: "More actions for Reports" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    const input = screen.getByDisplayValue("Reports");
    fireEvent.click(input);
    expectStillOnFiles();
  });

  it("still navigates into the folder when the tile is clicked", () => {
    renderCard({ view });
    fireEvent.click(screen.getByText("Reports"));
    expect(screen.getByTestId("location").textContent).toBe("/files?folder=folder-1");
  });

  it("has no non-interactive elements with click handlers", () => {
    const { container } = renderCard({ view, selectionActive: true });
    fireEvent.click(screen.getByRole("button", { name: "More actions for Reports" }));
    expect(container.querySelector(".fixed.inset-0")).toBeNull();
  });
});
