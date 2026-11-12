import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { FileItem } from "@/types";
import { FileCard } from "./file-card";

const file: FileItem = {
  id: "f1",
  name: "report.pdf",
  mimeType: "application/pdf",
  size: 1024,
  parentId: null,
  ownerId: "u1",
  ownerName: "Owner",
  isFolder: false,
  path: "/report.pdf",
  sharedWith: [],
  tags: [],
  versions: [],
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

function renderCard(props: Partial<React.ComponentProps<typeof FileCard>> = {}) {
  return render(
    <MemoryRouter initialEntries={["/files"]}>
      <Routes>
        <Route path="/files" element={<FileCard file={file} {...props} />} />
        <Route path="/files/:id" element={<p>file detail page</p>} />
      </Routes>
    </MemoryRouter>
  );
}

describe.each(["grid", "list"] as const)("FileCard (%s view)", (view) => {
  it("selects via a native, labelled checkbox without navigating", () => {
    const onSelect = vi.fn();
    renderCard({ view, selectionActive: true, onSelect });
    const checkbox = screen.getByRole("checkbox", { name: "Select report.pdf" });
    fireEvent.click(checkbox);
    expect(onSelect).toHaveBeenCalledWith("f1");
    expect(screen.queryByText("file detail page")).not.toBeInTheDocument();
  });

  it("reflects the selected prop on the checkbox", () => {
    renderCard({ view, selectionActive: true, selected: true });
    expect(screen.getByRole("checkbox", { name: "Select report.pdf" })).toBeChecked();
  });

  it("closes the actions menu with the backdrop button without navigating", () => {
    renderCard({ view });
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    expect(screen.getByRole("button", { name: "More actions" })).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getByRole("button", { name: "Close menu" }));
    expect(screen.queryByText("Rename")).not.toBeInTheDocument();
    expect(screen.queryByText("file detail page")).not.toBeInTheDocument();
  });

  it("closes the actions menu with Escape", () => {
    renderCard({ view });
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    expect(screen.getByText("Rename")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText("Rename")).not.toBeInTheDocument();
  });

  it("does not navigate while renaming, and submits the new name", () => {
    const onRename = vi.fn();
    renderCard({ view, onRename });
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.click(screen.getByText("Rename"));
    const input = screen.getByDisplayValue("report.pdf");
    fireEvent.click(input.parentElement!);
    expect(screen.queryByText("file detail page")).not.toBeInTheDocument();
    fireEvent.change(input, { target: { value: "final.pdf" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onRename).toHaveBeenCalledWith("f1", "final.pdf");
    expect(screen.queryByText("file detail page")).not.toBeInTheDocument();
  });

  it("still navigates to the file when the card is clicked", () => {
    renderCard({ view });
    fireEvent.click(screen.getByText("report.pdf"));
    expect(screen.getByText("file detail page")).toBeInTheDocument();
  });
});
