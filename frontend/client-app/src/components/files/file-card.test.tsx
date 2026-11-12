import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { FileItem } from "@/types";
import { FileCard } from "./file-card";

const file: FileItem = {
  id: "f1",
  name: "report.pdf",
  mimeType: "application/pdf",
  size: 2048,
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
  it("selects through the native checkbox, including from the keyboard", () => {
    const onSelect = vi.fn();
    renderCard({ view, selectionActive: true, onSelect });

    const checkbox = screen.getByRole("checkbox", { name: "Select report.pdf" });
    fireEvent.click(checkbox);
    expect(onSelect).toHaveBeenCalledWith("f1");

    checkbox.focus();
    expect(checkbox).toHaveFocus();
    fireEvent.click(checkbox);
    expect(onSelect).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("file detail page")).not.toBeInTheDocument();
  });

  it("opens an accessible menu that closes on Escape and on backdrop click without navigating", () => {
    renderCard({ view });

    const trigger = screen.getByRole("button", { name: "More actions for report.pdf" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.getAllByRole("menuitem").map((el) => el.textContent)).toEqual([
      "Rename",
      "Download",
      "Share",
      "Delete",
    ]);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "Close menu" }));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.queryByText("file detail page")).not.toBeInTheDocument();
  });

  it("renames inline without following the card link", () => {
    const onRename = vi.fn();
    renderCard({ view, onRename });

    fireEvent.click(screen.getByRole("button", { name: "More actions for report.pdf" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));

    const input = screen.getByDisplayValue("report.pdf");
    fireEvent.click(input);
    expect(screen.queryByText("file detail page")).not.toBeInTheDocument();

    fireEvent.change(input, { target: { value: "summary.pdf" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onRename).toHaveBeenCalledWith("f1", "summary.pdf");
  });

  it("still navigates when the card itself is clicked", () => {
    renderCard({ view });
    fireEvent.click(screen.getByText("report.pdf"));
    expect(screen.getByText("file detail page")).toBeInTheDocument();
  });
});
