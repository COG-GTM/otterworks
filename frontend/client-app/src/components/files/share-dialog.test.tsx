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
  it("exposes a labelled modal dialog and moves focus into it", () => {
    renderDialog();
    const dialog = screen.getByRole("dialog", { name: /share .report\.pdf./i });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveFocus();
  });

  it("closes when the native backdrop button is clicked", () => {
    const onClose = renderDialog();
    const backdrop = screen.getByRole("button", { name: "Close share dialog" });
    expect(backdrop.tagName).toBe("BUTTON");
    expect(backdrop).toHaveAttribute("tabindex", "-1");
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("lets outside clicks fall through the centering layer to the backdrop", () => {
    // JSDOM does not hit-test CSS, so pin the classes that route real clicks.
    renderDialog();
    const dialog = screen.getByRole("dialog");
    const centeringLayer = dialog.parentElement!;
    const backdrop = screen.getByRole("button", { name: "Close share dialog" });
    expect(centeringLayer).toHaveClass("pointer-events-none");
    expect(dialog).toHaveClass("pointer-events-auto");
    expect(backdrop.parentElement).toBe(centeringLayer.parentElement);
    expect(backdrop.compareDocumentPosition(centeringLayer)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
  });

  it("keeps Tab focus inside the dialog", () => {
    renderDialog();
    const dialog = screen.getByRole("dialog");
    const close = screen.getByRole("button", { name: "Close" });
    // The Share button is disabled until an email is typed, so the select is last.
    const permission = screen.getByRole("combobox");
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(permission).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(permission).toHaveFocus();
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("restores focus to the opener when it closes", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    const { unmount } = render(
      <ShareDialog
        fileId="file-1"
        fileName="report.pdf"
        sharedWith={[]}
        onShare={vi.fn()}
        onClose={vi.fn()}
      />
    );
    expect(screen.getByRole("dialog")).toHaveFocus();
    unmount();
    expect(opener).toHaveFocus();
    opener.remove();
  });

  it("closes on Escape and from the header close button", () => {
    const onClose = renderDialog();
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("does not close when interacting inside the dialog", () => {
    const onClose = renderDialog();
    fireEvent.click(screen.getByRole("dialog"));
    fireEvent.click(screen.getByRole("button", { name: /get link/i }));
    fireEvent.keyDown(document, { key: "Enter" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("attaches no click handlers to non-interactive elements", () => {
    renderDialog();
    const dialog = screen.getByRole("dialog");
    const root = dialog.parentElement!.parentElement!;
    const reactProps = (el: Element) => {
      const key = Object.keys(el).find((k) => k.startsWith("__reactProps$"));
      return key ? (el as unknown as Record<string, Record<string, unknown>>)[key] : {};
    };
    const offenders = [root, ...Array.from(root.querySelectorAll("*"))].filter(
      (el) =>
        typeof reactProps(el).onClick === "function" &&
        !["BUTTON", "A", "INPUT", "SELECT", "TEXTAREA"].includes(el.tagName)
    );
    expect(offenders.map((el) => el.outerHTML.slice(0, 80))).toEqual([]);
  });
});
