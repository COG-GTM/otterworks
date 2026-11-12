import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { FileCard } from "./file-card";
import type { FileItem } from "@/types";

const file: FileItem = {
  id: "file-1",
  name: "report.pdf",
  mimeType: "application/pdf",
  size: 1024,
  parentId: null,
  ownerId: "user-1",
  ownerName: "Otter",
  isFolder: false,
  path: "/report.pdf",
  sharedWith: [],
  versions: [],
  tags: [],
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

function renderCard(props: Partial<Parameters<typeof FileCard>[0]> = {}) {
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
  it("closes the actions menu on outside click without navigating", () => {
    renderCard({ view });
    const toggle = screen.getByRole("button", { name: "More actions" });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(screen.getByRole("button", { name: "Close menu" }));

    expect(screen.queryByRole("button", { name: "Close menu" })).not.toBeInTheDocument();
    expect(screen.queryByText("file detail page")).not.toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("closes the actions menu on Escape", () => {
    renderCard({ view });
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    expect(screen.getByRole("button", { name: "Rename" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("button", { name: "Rename" })).not.toBeInTheDocument();
  });

  it("toggles selection from the native checkbox", () => {
    const onSelect = vi.fn();
    renderCard({ view, selectionActive: true, onSelect });

    fireEvent.click(screen.getByRole("checkbox", { name: "Select report.pdf" }));

    expect(onSelect).toHaveBeenCalledWith("file-1");
    expect(screen.queryByText("file detail page")).not.toBeInTheDocument();
  });

  it("renames without navigating when clicking the rename input", () => {
    const onRename = vi.fn();
    renderCard({ view, onRename });
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));

    const input = screen.getByRole("textbox", { name: "New name" });
    fireEvent.click(input);
    expect(screen.queryByText("file detail page")).not.toBeInTheDocument();

    fireEvent.change(input, { target: { value: "summary.pdf" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onRename).toHaveBeenCalledWith("file-1", "summary.pdf");
  });
});
