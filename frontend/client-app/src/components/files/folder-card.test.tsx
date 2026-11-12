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
  ownerName: "Otter",
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
  return <output data-testid="location">{location.pathname + location.search}</output>;
}

function renderCard(props: Partial<React.ComponentProps<typeof FolderCard>> = {}) {
  return render(
    <MemoryRouter initialEntries={["/files"]}>
      <Routes>
        <Route
          path="/files"
          element={
            <>
              <FolderCard folder={folder} {...props} />
              <LocationProbe />
            </>
          }
        />
      </Routes>
    </MemoryRouter>
  );
}

describe.each(["grid", "list"] as const)("FolderCard (%s view)", (view) => {
  it("selects via the native checkbox without navigating", () => {
    const onSelect = vi.fn();
    renderCard({ view, selectionActive: true, onSelect });

    const checkbox = screen.getByRole("checkbox", { name: "Select Reports" });
    fireEvent.click(checkbox);

    expect(onSelect).toHaveBeenCalledWith("folder-1");
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/files$/);
  });

  it("closes the actions menu from the backdrop button without navigating", () => {
    renderCard({ view });

    const toggle = screen.getByRole("button", { name: "Actions for Reports" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close menu" }));

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/files$/);
  });

  it("closes the actions menu with Escape", () => {
    renderCard({ view });

    fireEvent.click(screen.getByRole("button", { name: "Actions for Reports" }));
    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("renames inline without navigating", () => {
    const onRename = vi.fn();
    renderCard({ view, onRename });

    fireEvent.click(screen.getByRole("button", { name: "Actions for Reports" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));

    const input = screen.getByRole("textbox");
    fireEvent.click(input);
    fireEvent.change(input, { target: { value: "Q3 Reports" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onRename).toHaveBeenCalledWith("folder-1", "Q3 Reports");
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/files$/);
  });

  it("opens the folder when the card link is clicked", () => {
    renderCard({ view });

    fireEvent.click(screen.getByText("Reports"));

    expect(screen.getByTestId("location")).toHaveTextContent("/files?folder=folder-1");
  });
});
