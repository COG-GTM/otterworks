import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { FileCard } from "./file-card";
import { useAuthStore } from "@/stores/auth-store";
import type { FileItem } from "@/types";

const baseFile: FileItem = {
  id: "f1",
  name: "report.pdf",
  mimeType: "application/pdf",
  size: 2048,
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
};

function renderCard(props: Partial<React.ComponentProps<typeof FileCard>> = {}) {
  return render(
    <MemoryRouter>
      <FileCard file={baseFile} {...props} />
    </MemoryRouter>,
  );
}

function openMenu() {
  const trigger = screen.getAllByRole("button").find((b) => !b.getAttribute("aria-label"))!;
  fireEvent.click(trigger);
}

describe.each(["grid", "list"] as const)("FileCard (%s view)", (view) => {
  beforeEach(() => {
    localStorage.clear();
    useAuthStore.setState({ user: { id: "u1" } as never, isAuthenticated: true, isLoading: false });
  });

  it("links files and folders to the right route", () => {
    const { unmount } = renderCard({ view });
    expect(screen.getByRole("link")).toHaveAttribute("href", "/files/f1");
    unmount();
    renderCard({ view, file: { ...baseFile, id: "d1", isFolder: true } });
    expect(screen.getByRole("link")).toHaveAttribute("href", "/files?folder=d1");
  });

  it("toggles star state and notifies the parent", () => {
    const onStarToggle = vi.fn();
    renderCard({ view, onStarToggle });
    fireEvent.click(screen.getByRole("button", { name: "Star" }));
    expect(screen.getByRole("button", { name: "Unstar" })).toBeInTheDocument();
    expect(onStarToggle).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Unstar" }));
    expect(screen.getByRole("button", { name: "Star" })).toBeInTheDocument();
  });

  it("does not star without a signed-in user", () => {
    useAuthStore.setState({ user: null });
    const onStarToggle = vi.fn();
    renderCard({ view, onStarToggle });
    fireEvent.click(screen.getByRole("button", { name: "Star" }));
    expect(screen.getByRole("button", { name: "Star" })).toBeInTheDocument();
    expect(onStarToggle).not.toHaveBeenCalled();
  });

  it("shows the selection checkbox only when selection is active", () => {
    const onSelect = vi.fn();
    const { rerender } = renderCard({ view, onSelect });
    expect(screen.queryByRole("checkbox")).toBeNull();
    rerender(
      <MemoryRouter>
        <FileCard file={baseFile} view={view} onSelect={onSelect} selectionActive selected />
      </MemoryRouter>,
    );
    const box = screen.getByRole("checkbox");
    expect(box).toBeChecked();
    fireEvent.click(box);
    expect(onSelect).toHaveBeenCalledWith("f1");
  });

  it("menu actions call the right handlers", () => {
    const onDelete = vi.fn();
    const onShare = vi.fn();
    const onDownload = vi.fn();
    renderCard({ view, onDelete, onShare, onDownload });
    openMenu();
    fireEvent.click(screen.getByText("Download"));
    expect(onDownload).toHaveBeenCalledWith("f1", "report.pdf");
    expect(screen.queryByText("Share")).toBeNull();
    openMenu();
    fireEvent.click(screen.getByText("Share"));
    expect(onShare).toHaveBeenCalledWith("f1");
    openMenu();
    fireEvent.click(screen.getByText("Delete"));
    expect(onDelete).toHaveBeenCalledWith("f1");
  });

  it("hides Download for folders", () => {
    renderCard({ view, file: { ...baseFile, isFolder: true } });
    openMenu();
    expect(screen.queryByText("Download")).toBeNull();
    expect(screen.getByText("Rename")).toBeInTheDocument();
  });

  it("renames on Enter with a trimmed, changed name and selects the basename", () => {
    const onRename = vi.fn();
    renderCard({ view, onRename });
    openMenu();
    fireEvent.click(screen.getByText("Rename"));
    const input = screen.getByRole("textbox") as HTMLInputElement;
    expect(input).toHaveValue("report.pdf");
    expect(document.activeElement).toBe(input);
    expect([input.selectionStart, input.selectionEnd]).toEqual([0, 6]);
    fireEvent.change(input, { target: { value: "  final.pdf  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.blur(input);
    expect(onRename).toHaveBeenCalledTimes(1);
    expect(onRename).toHaveBeenCalledWith("f1", "final.pdf");
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("saves the rename on blur", () => {
    const onRename = vi.fn();
    renderCard({ view, onRename });
    openMenu();
    fireEvent.click(screen.getByText("Rename"));
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "blurred.pdf" } });
    fireEvent.blur(input);
    expect(onRename).toHaveBeenCalledTimes(1);
    expect(onRename).toHaveBeenCalledWith("f1", "blurred.pdf");
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("does not rename when the name is unchanged or blank", () => {
    const onRename = vi.fn();
    renderCard({ view, onRename });
    openMenu();
    fireEvent.click(screen.getByText("Rename"));
    fireEvent.blur(screen.getByRole("textbox"));
    openMenu();
    fireEvent.click(screen.getByText("Rename"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "   " } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(onRename).not.toHaveBeenCalled();
  });

  it("Escape cancels the rename and discards the edit", () => {
    const onRename = vi.fn();
    renderCard({ view, onRename });
    openMenu();
    fireEvent.click(screen.getByText("Rename"));
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "other.pdf" } });
    fireEvent.keyDown(input, { key: "Escape" });
    fireEvent.blur(input);
    expect(onRename).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByText("report.pdf")).toBeInTheDocument();
  });
});
