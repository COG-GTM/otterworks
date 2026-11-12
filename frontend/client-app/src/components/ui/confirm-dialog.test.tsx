import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "./confirm-dialog";

function renderDialog(open = true) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  const utils = render(
    <ConfirmDialog
      open={open}
      title="Empty trash"
      description="This action cannot be undone."
      confirmLabel="Delete all"
      variant="destructive"
      onConfirm={onConfirm}
      onCancel={onCancel}
    />
  );
  return { ...utils, onConfirm, onCancel };
}

describe("ConfirmDialog", () => {
  // jsdom does not implement the modal <dialog> API.
  const showModal = vi.fn(function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  });
  const close = vi.fn(function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  });

  beforeEach(() => {
    Object.assign(HTMLDialogElement.prototype, { showModal, close });
    vi.clearAllMocks();
  });

  it("renders a native modal <dialog> labelled by its title and description", () => {
    renderDialog();
    const dialog = screen.getByRole("dialog", { name: "Empty trash" });
    expect(dialog.tagName).toBe("DIALOG");
    expect(dialog).not.toHaveAttribute("role");
    expect(dialog).toHaveAccessibleDescription("This action cannot be undone.");
    expect(showModal).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  it("renders nothing when closed", () => {
    renderDialog(false);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(showModal).not.toHaveBeenCalled();
  });

  it("invokes onConfirm and onCancel from the buttons", () => {
    const { onConfirm, onCancel } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Delete all" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("routes Escape (cancel event) to onCancel without closing natively", () => {
    const { onCancel } = renderDialog();
    const dialog = screen.getByRole("dialog");
    const cancel = new Event("cancel", { cancelable: true });
    dialog.dispatchEvent(cancel);
    expect(cancel.defaultPrevented).toBe(true);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("cancels on backdrop click but not on clicks inside the panel", () => {
    const { onCancel } = renderDialog();
    fireEvent.click(screen.getByText("This action cannot be undone."));
    expect(onCancel).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("dialog"));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("closes the native dialog when unmounted", () => {
    const { rerender, onConfirm, onCancel } = renderDialog();
    rerender(
      <ConfirmDialog
        open={false}
        title="Empty trash"
        description="This action cannot be undone."
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    );
    expect(close).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
