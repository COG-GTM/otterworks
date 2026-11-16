import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import toast from "react-hot-toast";
import { CopyLinkButton } from "./copy-link-button";

vi.mock("react-hot-toast", () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

const originalClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");

function mockClipboard(value: unknown) {
  Object.defineProperty(navigator, "clipboard", { value, configurable: true });
}

describe("CopyLinkButton", () => {
  beforeEach(() => {
    vi.mocked(toast.success).mockClear();
    vi.mocked(toast.error).mockClear();
  });

  afterEach(() => {
    if (originalClipboard) {
      Object.defineProperty(navigator, "clipboard", originalClipboard);
    } else {
      delete (navigator as { clipboard?: unknown }).clipboard;
    }
  });

  it("copies the current page URL and shows a success toast", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    mockClipboard({ writeText });
    window.history.pushState({}, "", "/files/abc-123");

    render(<CopyLinkButton />);
    fireEvent.click(screen.getByRole("button", { name: "Copy link" }));

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Link copied"));
    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/files/abc-123`);
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("copies an explicit URL when one is provided", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    mockClipboard({ writeText });

    render(<CopyLinkButton url="https://otterworks.app/files/xyz" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy link" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("https://otterworks.app/files/xyz"));
  });

  it("shows an error toast when the clipboard API is unavailable", async () => {
    mockClipboard(undefined);

    render(<CopyLinkButton />);
    fireEvent.click(screen.getByRole("button", { name: "Copy link" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("shows an error toast when writing to the clipboard fails", async () => {
    mockClipboard({ writeText: vi.fn().mockRejectedValue(new Error("denied")) });

    render(<CopyLinkButton />);
    fireEvent.click(screen.getByRole("button", { name: "Copy link" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    expect(toast.success).not.toHaveBeenCalled();
  });
});
