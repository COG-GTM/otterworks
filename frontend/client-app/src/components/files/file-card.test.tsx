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
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
  versions: [],
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
  it("selects through a native, labelled checkbox", () => {
    const onSelect = vi.fn();
    renderCard({ view, selectionActive: true, onSelect });
    const checkbox = screen.getByRole("checkbox", { name: "Select report.pdf" });
    fireEvent.click(checkbox);
    expect(onSelect).toHaveBeenCalledWith("f1");
    expect(screen.queryByText("file detail page")).not.toBeInTheDocument();
  });

  it("does not navigate while renaming", () => {
    const onRename = vi.fn();
    renderCard({ view, onRename });
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    const input = screen.getByRole("textbox");
    fireEvent.click(input.parentElement!);
    expect(screen.queryByText("file detail page")).not.toBeInTheDocument();
    fireEvent.change(input, { target: { value: "renamed.pdf" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onRename).toHaveBeenCalledWith("f1", "renamed.pdf");
  });

  it("does not navigate when clicking elsewhere on the card ends a rename", () => {
    renderCard({ view, onRename: vi.fn() });
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    const input = screen.getByRole("textbox");
    const link = screen.getByRole("link");
    fireEvent.mouseDown(link);
    fireEvent.blur(input);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    fireEvent.click(link);
    expect(screen.queryByText("file detail page")).not.toBeInTheDocument();
    fireEvent.mouseDown(link);
    fireEvent.click(link);
    expect(screen.getByText("file detail page")).toBeInTheDocument();
  });

  it("closes the menu with Escape", () => {
    renderCard({ view });
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("closes the menu on an outside click without navigating", () => {
    renderCard({ view });
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.click(screen.getByRole("button", { name: "Close menu" }));
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(screen.queryByText("file detail page")).not.toBeInTheDocument();
  });

  it("still navigates to the file when the card is clicked", () => {
    renderCard({ view });
    fireEvent.click(screen.getByText("report.pdf"));
    expect(screen.getByText("file detail page")).toBeInTheDocument();
  });
});
