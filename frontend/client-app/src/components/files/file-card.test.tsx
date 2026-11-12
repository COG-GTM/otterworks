import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { FileItem } from "@/types";
import { FileCard } from "./file-card";

const file: FileItem = {
  id: "file-1",
  name: "report.pdf",
  mimeType: "application/pdf",
  size: 2048,
  parentId: null,
  ownerId: "user-1",
  ownerName: "Otter",
  isFolder: false,
  path: "/report.pdf",
  sharedWith: [],
  tags: [],
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
  versions: [],
};

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderCard(props: Partial<React.ComponentProps<typeof FileCard>> = {}) {
  return render(
    <MemoryRouter initialEntries={["/files"]}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              <FileCard file={file} {...props} />
              <LocationProbe />
            </>
          }
        />
      </Routes>
    </MemoryRouter>
  );
}

describe.each(["grid", "list"] as const)("FileCard (%s view)", (view) => {
  it("selects the file through a native, labelled checkbox", () => {
    const onSelect = vi.fn();
    renderCard({ view, selectionActive: true, onSelect });

    const checkbox = screen.getByRole("checkbox", { name: "Select report.pdf" });
    fireEvent.click(checkbox);

    expect(onSelect).toHaveBeenCalledWith("file-1");
    expect(screen.getByTestId("location").textContent).toBe("/files");
  });

  it("closes the actions menu with the backdrop button without navigating", () => {
    renderCard({ view });

    const trigger = screen.getByRole("button", { name: "More actions" });
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    const backdrop = screen.getByRole("button", { name: "Close menu" });
    expect(backdrop.tagName).toBe("BUTTON");
    fireEvent.click(backdrop);

    expect(screen.queryByRole("button", { name: "Rename" })).not.toBeInTheDocument();
    expect(screen.getByTestId("location").textContent).toBe("/files");
  });

  it("closes the actions menu with Escape", () => {
    renderCard({ view });

    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    expect(screen.getByRole("button", { name: "Rename" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("button", { name: "Rename" })).not.toBeInTheDocument();
  });

  it("does not navigate while renaming and still submits the new name", () => {
    const onRename = vi.fn();
    renderCard({ view, onRename });

    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));

    const input = screen.getByDisplayValue("report.pdf");
    fireEvent.click(input.parentElement as HTMLElement);
    expect(screen.getByTestId("location").textContent).toBe("/files");

    fireEvent.change(input, { target: { value: "summary.pdf" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onRename).toHaveBeenCalledWith("file-1", "summary.pdf");
  });

  it("does not navigate when clicking elsewhere on the card to end a rename", () => {
    const onRename = vi.fn();
    renderCard({ view, onRename });

    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));

    const input = screen.getByDisplayValue("report.pdf");
    fireEvent.change(input, { target: { value: "summary.pdf" } });
    const link = screen.getByRole("link");
    fireEvent.mouseDown(link);
    fireEvent.blur(input);
    fireEvent.click(link);

    expect(onRename).toHaveBeenCalledWith("file-1", "summary.pdf");
    expect(screen.getByTestId("location").textContent).toBe("/files");

    fireEvent.mouseDown(link);
    fireEvent.click(link);
    expect(screen.getByTestId("location").textContent).toBe("/files/file-1");
  });

  it("navigates to the file when not renaming", () => {
    renderCard({ view });

    fireEvent.click(screen.getByText("report.pdf"));

    expect(screen.getByTestId("location").textContent).toBe("/files/file-1");
  });
});
