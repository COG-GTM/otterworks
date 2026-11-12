import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { FileItem } from "@/types";
import { FileCard } from "./file-card";
import { FolderCard } from "./folder-card";

const item: FileItem = {
  id: "f1",
  name: "report.pdf",
  mimeType: "application/pdf",
  size: 1024,
  parentId: null,
  ownerId: "u1",
  ownerName: "Otter",
  isFolder: false,
  path: "/report.pdf",
  sharedWith: [],
  tags: [],
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
  versions: [],
} as unknown as FileItem;

describe.each(["grid", "list"] as const)("selection checkbox (%s view)", (view) => {
  it("is a labelled, focusable control that toggles file selection", () => {
    const onSelect = vi.fn();
    render(
      <MemoryRouter>
        <FileCard file={item} view={view} selectionActive onSelect={onSelect} />
      </MemoryRouter>
    );
    const checkbox = screen.getByRole("checkbox", { name: "Select report.pdf" });
    expect(checkbox).toBeEnabled();
    expect(checkbox.tabIndex).toBe(0);
    checkbox.focus();
    expect(checkbox).toHaveFocus();
    fireEvent.click(checkbox);
    expect(onSelect).toHaveBeenCalledWith("f1");
    expect(checkbox.closest("a")).toBeNull();
  });

  it("is a labelled, focusable control that toggles folder selection", () => {
    const onSelect = vi.fn();
    render(
      <MemoryRouter>
        <FolderCard
          folder={{ ...item, id: "d1", name: "Reports", isFolder: true }}
          view={view}
          selectionActive
          onSelect={onSelect}
        />
      </MemoryRouter>
    );
    const checkbox = screen.getByRole("checkbox", { name: "Select Reports" });
    expect(checkbox).toBeEnabled();
    expect(checkbox.tabIndex).toBe(0);
    fireEvent.click(checkbox);
    expect(onSelect).toHaveBeenCalledWith("d1");
  });
});

function CurrentUrl() {
  const { pathname, search } = useLocation();
  return <output data-testid="url">{pathname + search}</output>;
}

describe.each(["grid", "list"] as const)("menu backdrop (%s view)", (view) => {
  it.each([
    ["file", (v: typeof view) => <FileCard file={item} view={v} />],
    ["folder", (v: typeof view) => <FolderCard folder={{ ...item, isFolder: true }} view={v} />],
  ])("closes the %s menu without following the card link", (_kind, card) => {
    const { container } = render(
      <MemoryRouter initialEntries={["/files"]}>
        {card(view)}
        <CurrentUrl />
      </MemoryRouter>
    );
    fireEvent.click(screen.getByRole("button", { name: "" }));
    expect(screen.getByRole("button", { name: /rename/i })).toBeInTheDocument();

    const backdrop = container.querySelector('[aria-hidden="true"].fixed.inset-0');
    expect(backdrop).not.toBeNull();
    fireEvent.click(backdrop!);

    expect(screen.queryByRole("button", { name: /rename/i })).toBeNull();
    expect(screen.getByTestId("url")).toHaveTextContent(/^\/files$/);
  });
});
