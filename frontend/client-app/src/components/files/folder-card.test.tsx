import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { FileItem } from "@/types";
import { FolderCard } from "./folder-card";

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
        <Route path="*" element={<FolderCard folder={folder} {...props} />} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>
  );
}

describe.each(["grid", "list"] as const)("FolderCard (%s view)", (view) => {
  it("selects via a native, labelled checkbox", () => {
    const onSelect = vi.fn();
    renderCard({ view, selectionActive: true, onSelect });
    const checkbox = screen.getByRole("checkbox", { name: "Select Reports" });
    fireEvent.click(checkbox);
    expect(onSelect).toHaveBeenCalledWith("folder-1");
    expect(screen.getByTestId("location")).toHaveTextContent("/home");
  });

  it.each([true, false])("reflects selected=%s on the checkbox", (selected) => {
    renderCard({ view, selectionActive: true, selected, onSelect: vi.fn() });
    const checkbox = screen.getByRole("checkbox", { name: "Select Reports" });
    if (selected) expect(checkbox).toBeChecked();
    else expect(checkbox).not.toBeChecked();
  });

  it("closes the actions menu from the backdrop button without navigating", () => {
    renderCard({ view });
    const trigger = screen.getByRole("button", { name: "More actions for Reports" });
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getByRole("button", { name: "Close menu" }));
    expect(screen.queryByRole("button", { name: "Rename" })).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByTestId("location")).toHaveTextContent("/home");
  });

  it("closes the actions menu with Escape", () => {
    renderCard({ view });
    fireEvent.click(screen.getByRole("button", { name: "More actions for Reports" }));
    expect(screen.getByRole("button", { name: "Rename" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("button", { name: "Rename" })).not.toBeInTheDocument();
  });

  it("renames inline without navigating into the folder", () => {
    const onRename = vi.fn();
    renderCard({ view, onRename });
    fireEvent.click(screen.getByRole("button", { name: "More actions for Reports" }));
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    const input = screen.getByRole("textbox", { name: "Folder name" });
    fireEvent.click(input);
    fireEvent.click(input.parentElement!);
    expect(screen.getByTestId("location")).toHaveTextContent("/home");
    fireEvent.change(input, { target: { value: "Q3 Reports" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onRename).toHaveBeenCalledWith("folder-1", "Q3 Reports");
  });

  it("does not navigate when a click elsewhere on the folder blurs the rename input", () => {
    const onRename = vi.fn();
    renderCard({ view, onRename });
    fireEvent.click(screen.getByRole("button", { name: "More actions for Reports" }));
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    const input = screen.getByRole("textbox", { name: "Folder name" });
    fireEvent.change(input, { target: { value: "Q3 Reports" } });
    const link = input.closest("a")!;
    fireEvent.mouseDown(link);
    fireEvent.blur(input);
    fireEvent.click(link, { detail: 1 });
    expect(onRename).toHaveBeenCalledWith("folder-1", "Q3 Reports");
    expect(screen.getByTestId("location")).toHaveTextContent("/home");
    fireEvent.mouseDown(link);
    fireEvent.click(link, { detail: 1 });
    expect(screen.getByTestId("location")).toHaveTextContent("/files?folder=folder-1");
  });

  it("opens the folder from the keyboard after a rename submitted with Enter", () => {
    renderCard({ view, onRename: vi.fn() });
    fireEvent.click(screen.getByRole("button", { name: "More actions for Reports" }));
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    const input = screen.getByRole("textbox", { name: "Folder name" });
    const link = input.closest("a")!;
    fireEvent.mouseDown(input);
    fireEvent.click(input, { detail: 1 });
    fireEvent.change(input, { target: { value: "Q3 Reports" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.click(link);
    expect(screen.getByTestId("location")).toHaveTextContent("/files?folder=folder-1");
  });
});
