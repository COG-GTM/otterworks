import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ShareDialog } from "./share-dialog";

function renderDialog(onClose = vi.fn()) {
  render(
    <ShareDialog
      fileId="file-1"
      fileName="report.pdf"
      sharedWith={[]}
      onShare={vi.fn().mockResolvedValue(undefined)}
      onClose={onClose}
    />
  );
  return onClose;
}

describe("ShareDialog", () => {
  it("exposes a labelled modal dialog", () => {
    renderDialog();
    const dialog = screen.getByRole("dialog", { name: /share .report\.pdf./i });
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("closes when the backdrop button is clicked", () => {
    const onClose = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Close share dialog" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not close when clicking inside the dialog", () => {
    const onClose = renderDialog();
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes on Escape", () => {
    const onClose = renderDialog();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes from the header close button", () => {
    const onClose = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("keeps the backdrop out of the tab order", () => {
    renderDialog();
    expect(screen.getByRole("button", { name: "Close share dialog" })).toHaveAttribute("tabindex", "-1");
  });

  it("moves focus into the dialog and traps Tab inside it", () => {
    renderDialog();
    const dialog = screen.getByRole("dialog");
    const close = screen.getByRole("button", { name: "Close" });
    expect(close).toHaveFocus();

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    const focusable = dialog.querySelectorAll<HTMLElement>("button:not([disabled]), input, select");
    const last = focusable[focusable.length - 1];
    expect(last).toHaveFocus();

    fireEvent.keyDown(document, { key: "Tab" });
    expect(close).toHaveFocus();
  });

  it("restores focus to the opener on unmount", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    const { unmount } = render(
      <ShareDialog fileId="f" fileName="a.txt" sharedWith={[]} onShare={vi.fn()} onClose={vi.fn()} />
    );
    expect(opener).not.toHaveFocus();
    unmount();
    expect(opener).toHaveFocus();
    opener.remove();
  });
});
