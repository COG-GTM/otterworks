import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
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

function renderCard(props: Partial<Parameters<typeof FolderCard>[0]> = {}) {
  return render(
    <MemoryRouter>
      <FolderCard folder={folder} {...props} />
    </MemoryRouter>
  );
}

describe.each(["grid", "list"] as const)("FolderCard (%s view)", (view) => {
  it("selects with Space after tabbing to the labelled checkbox", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    renderCard({ view, selectionActive: true, onSelect });

    await user.tab();
    const checkbox = screen.getByRole("checkbox", { name: "Select Reports" });
    expect(checkbox).toHaveFocus();

    await user.keyboard(" ");
    expect(onSelect).toHaveBeenCalledWith("folder-1");
  });

  it("selects with a mouse click without navigating", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    renderCard({ view, selectionActive: true, onSelect });

    await user.click(screen.getByRole("checkbox", { name: "Select Reports" }));
    expect(onSelect).toHaveBeenCalledWith("folder-1");
  });

  it("reflects the selected state", () => {
    renderCard({ view, selectionActive: true, selected: true });
    expect(screen.getByRole("checkbox", { name: "Select Reports" })).toBeChecked();
  });

  it("opens the actions menu with Enter and closes it with Escape, restoring focus", async () => {
    const user = userEvent.setup();
    renderCard({ view });
    const trigger = screen.getByRole("button", { name: "More actions for Reports" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    trigger.focus();
    await user.keyboard("{Enter}");
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    await user.tab();
    expect(screen.getByRole("button", { name: /rename/i })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: /rename/i })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("renames from the keyboard: Enter on Rename, type, Enter to submit", async () => {
    const user = userEvent.setup();
    const onRename = vi.fn();
    renderCard({ view, onRename });

    screen.getByRole("button", { name: "More actions for Reports" }).focus();
    await user.keyboard("{Enter}");
    await user.tab();
    await user.keyboard("{Enter}");

    const input = screen.getByDisplayValue("Reports");
    expect(input).toHaveFocus();
    await user.clear(input);
    await user.type(input, "Q3 Reports{Enter}");

    expect(onRename).toHaveBeenCalledWith("folder-1", "Q3 Reports");
    expect(screen.queryByDisplayValue("Q3 Reports")).not.toBeInTheDocument();
  });
});
