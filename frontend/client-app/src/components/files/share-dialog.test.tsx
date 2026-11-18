import { useState } from "react";
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

function ShareHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>Share</button>
      {open && (
        <ShareDialog
          fileId="file-1"
          fileName="report.pdf"
          sharedWith={[]}
          onShare={vi.fn().mockResolvedValue(undefined)}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

describe("ShareDialog", () => {
  it("closes when Esc is pressed", () => {
    const onClose = renderDialog();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not close on other keys", () => {
    const onClose = renderDialog();
    fireEvent.keyDown(document, { key: "Enter" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes when the backdrop outside the dialog is clicked", () => {
    const onClose = renderDialog();
    fireEvent.click(screen.getByTestId("share-dialog-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("stays open when clicking inside the dialog", () => {
    const onClose = renderDialog();
    const dialog = screen.getByRole("dialog", { name: /share/i });
    fireEvent.click(dialog);
    fireEvent.click(screen.getByText(/report\.pdf/));
    fireEvent.click(screen.getByPlaceholderText(/email/i));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("returns focus to the Share button after closing with Esc", () => {
    render(<ShareHarness />);
    const shareButton = screen.getByRole("button", { name: "Share" });
    shareButton.focus();
    fireEvent.click(shareButton);
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(shareButton).toHaveFocus();
  });

  it("returns focus to the Share button after closing via the backdrop", () => {
    render(<ShareHarness />);
    const shareButton = screen.getByRole("button", { name: "Share" });
    shareButton.focus();
    fireEvent.click(shareButton);

    fireEvent.click(screen.getByTestId("share-dialog-backdrop"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(shareButton).toHaveFocus();
  });
});
