import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";
import toast from "react-hot-toast";
import { filesApi } from "@/lib/api";
import type { SharedUser } from "@/types";
import { ShareDialog } from "./share-dialog";

vi.mock("react-hot-toast", () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api", () => ({
  filesApi: {
    updateSharePermission: vi.fn(),
    removeShare: vi.fn(),
  },
}));

const alice: SharedUser = { userId: "user-alice-0001", name: "Alice", email: "alice@example.com", permission: "view" } as SharedUser;
const bob: SharedUser = { userId: "user-bob-000002", name: "", email: "", permission: "edit" } as SharedUser;
const owner: SharedUser = { userId: "owner-1", name: "Olive", email: "olive@example.com", permission: "edit" } as SharedUser;

type Props = Parameters<typeof ShareDialog>[0];

function renderDialog(overrides: Partial<Props> = {}) {
  const props: Props = {
    fileId: "file-123",
    fileName: "report.pdf",
    sharedWith: [],
    onShare: vi.fn().mockResolvedValue(undefined),
    onClose: vi.fn(),
    ...overrides,
  };
  render(<ShareDialog {...props} />);
  return props;
}

function axiosFailure(data: unknown) {
  return new AxiosError("Request failed", "ERR_BAD_RESPONSE", undefined, undefined, {
    data,
    status: 500,
    statusText: "Internal Server Error",
    headers: {},
    config: { headers: new AxiosHeaders() },
  });
}

function shareWith(email: string) {
  fireEvent.change(screen.getByPlaceholderText("Add people by email"), { target: { value: email } });
  fireEvent.click(screen.getByRole("button", { name: "Share" }));
}

describe("ShareDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the file name and closes from the header and backdrop", () => {
    const props = renderDialog();
    expect(screen.getByRole("heading")).toHaveTextContent("Share \u201creport.pdf\u201d");
    fireEvent.click(screen.getAllByRole("button")[0]);
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it("disables Share until an email is entered", () => {
    renderDialog();
    expect(screen.getByRole("button", { name: "Share" })).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText("Add people by email"), { target: { value: "   " } });
    expect(screen.getByRole("button", { name: "Share" })).toBeDisabled();
  });

  it("shares with the trimmed email and selected permission, then clears the input", async () => {
    const props = renderDialog();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "edit" } });
    shareWith("  carol@example.com ");
    await waitFor(() => expect(props.onShare).toHaveBeenCalledWith("carol@example.com", "edit"));
    await waitFor(() => expect(screen.getByPlaceholderText("Add people by email")).toHaveValue(""));
    expect(toast.success).toHaveBeenCalledWith("Shared with carol@example.com");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shares when Enter is pressed in the email field", async () => {
    const props = renderDialog();
    const input = screen.getByPlaceholderText("Add people by email");
    fireEvent.change(input, { target: { value: "dave@example.com" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(props.onShare).toHaveBeenCalledWith("dave@example.com", "view"));
  });

  it("shows Sharing... while the share is in flight", async () => {
    let resolve!: () => void;
    renderDialog({ onShare: vi.fn(() => new Promise<void>((r) => (resolve = r))) });
    shareWith("erin@example.com");
    expect(await screen.findByRole("button", { name: "Sharing..." })).toBeDisabled();
    resolve();
    await waitFor(() => expect(screen.getByRole("button", { name: "Share" })).toBeInTheDocument());
  });

  it.each([
    [{ error: "event_error", message: "SNS publish failed" }, "Sharing failed. AWS SNS publish failed"],
    [{ error: "storage_error", message: "S3 unavailable" }, "Sharing failed. AWS S3 unavailable"],
    [{ error: "validation_error", message: "User not found" }, "Sharing failed: User not found"],
    [{ error: "event_error" }, "Sharing failed."],
  ])("maps axios error %j to %s", async (data, expected) => {
    const props = renderDialog({ onShare: vi.fn().mockRejectedValue(axiosFailure(data)) });
    shareWith("frank@example.com");
    expect(await screen.findByRole("alert")).toHaveTextContent(expected);
    expect(toast.error).toHaveBeenCalledWith(expected);
    expect(screen.getByPlaceholderText("Add people by email")).toHaveValue("frank@example.com");
    expect(props.onShare).toHaveBeenCalledTimes(1);
  });

  it("shows a generic message for non-axios errors and clears it on the next success", async () => {
    const onShare = vi.fn().mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce(undefined);
    renderDialog({ onShare });
    shareWith("gina@example.com");
    expect(await screen.findByRole("alert")).toHaveTextContent(/^Sharing failed\.$/);
    fireEvent.click(screen.getByRole("button", { name: "Share" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("shows the empty state when nobody has access and there is no owner", () => {
    renderDialog();
    expect(screen.getAllByText("No one else has access yet")).toHaveLength(1);
  });

  it("shows the owner row and a single empty state when only the owner has access", () => {
    renderDialog({ ownerId: "owner-1", ownerName: "olive", ownerEmail: "olive@example.com", sharedWith: [owner] });
    expect(screen.getByText("olive")).toBeInTheDocument();
    expect(screen.getByText("O")).toBeInTheDocument();
    expect(screen.getByText("olive@example.com")).toBeInTheDocument();
    expect(screen.getAllByText("Owner")).toHaveLength(1);
    expect(screen.getAllByText("No one else has access yet")).toHaveLength(1);
    expect(screen.queryByTitle("Remove access")).not.toBeInTheDocument();
  });

  it("falls back to default owner labels", () => {
    renderDialog({ ownerId: "owner-1", sharedWith: [alice] });
    expect(screen.getAllByText("Owner")).toHaveLength(2);
    expect(screen.getByText("O")).toBeInTheDocument();
    expect(screen.queryByText("No one else has access yet")).not.toBeInTheDocument();
  });

  it("lists shared users, excluding the owner, using resolved names and fallbacks", () => {
    renderDialog({
      ownerId: "owner-1",
      sharedWith: [owner, alice, bob],
      resolvedUsers: { "user-alice-0001": { name: "Alice Resolved", email: "alice.r@example.com" } },
    });
    expect(screen.getByText("Alice Resolved")).toBeInTheDocument();
    expect(screen.getByText("alice.r@example.com")).toBeInTheDocument();
    expect(screen.getByText("user-bob")).toBeInTheDocument();
    expect(screen.getByText("U")).toBeInTheDocument();
    expect(screen.queryByText("Olive")).not.toBeInTheDocument();
    expect(screen.getAllByTitle("Remove access")).toHaveLength(2);
    const selects = screen.getAllByRole("combobox");
    expect(selects.map((s) => (s as HTMLSelectElement).value)).toEqual(["view", "view", "edit"]);
  });

  it("changes permission through the callback when provided", async () => {
    const onPermissionChange = vi.fn().mockResolvedValue(undefined);
    renderDialog({ sharedWith: [alice], onPermissionChange });
    fireEvent.change(screen.getAllByRole("combobox")[1], { target: { value: "edit" } });
    await waitFor(() => expect(onPermissionChange).toHaveBeenCalledWith("user-alice-0001", "edit"));
    expect(filesApi.updateSharePermission).not.toHaveBeenCalled();
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Permission updated"));
  });

  it("changes permission through filesApi and reports failures", async () => {
    vi.mocked(filesApi.updateSharePermission).mockRejectedValue(new Error("nope"));
    renderDialog({ sharedWith: [alice] });
    fireEvent.change(screen.getAllByRole("combobox")[1], { target: { value: "edit" } });
    await waitFor(() => expect(filesApi.updateSharePermission).toHaveBeenCalledWith("file-123", "user-alice-0001", "edit"));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Failed to update permission"));
  });

  it("disables the row controls while a permission update is pending", async () => {
    let resolve!: () => void;
    renderDialog({ sharedWith: [alice], onPermissionChange: vi.fn(() => new Promise<void>((r) => (resolve = r))) });
    const select = screen.getAllByRole("combobox")[1];
    fireEvent.change(select, { target: { value: "edit" } });
    await waitFor(() => expect(select).toBeDisabled());
    expect(select).toHaveClass("cursor-wait");
    expect(screen.getByTitle("Remove access")).toBeDisabled();
    resolve();
    await waitFor(() => expect(select).not.toBeDisabled());
  });

  it("removes access through the callback when provided", async () => {
    const onRemoveAccess = vi.fn().mockResolvedValue(undefined);
    renderDialog({ sharedWith: [alice], onRemoveAccess });
    fireEvent.click(screen.getByTitle("Remove access"));
    await waitFor(() => expect(onRemoveAccess).toHaveBeenCalledWith("user-alice-0001"));
    expect(filesApi.removeShare).not.toHaveBeenCalled();
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Access removed"));
  });

  it("removes access through filesApi and reports failures", async () => {
    vi.mocked(filesApi.removeShare).mockRejectedValue(new Error("nope"));
    renderDialog({ sharedWith: [alice] });
    fireEvent.click(screen.getByTitle("Remove access"));
    await waitFor(() => expect(filesApi.removeShare).toHaveBeenCalledWith("file-123", "user-alice-0001"));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Failed to remove access"));
  });

  it("toggles general link access on the Get link tab", () => {
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /Get link/ }));
    expect(screen.queryByPlaceholderText("Add people by email")).not.toBeInTheDocument();
    expect(screen.getByText(`${window.location.origin}/files/file-123`)).toBeInTheDocument();
    expect(screen.getByText("Only people with access can open this link")).toBeInTheDocument();
    const restricted = screen.getByRole("button", { name: /Restricted/ });
    const anyone = screen.getByRole("button", { name: /Anyone with the link/ });
    expect(restricted).toHaveClass("bg-otter-50");
    expect(anyone).not.toHaveClass("bg-otter-50");

    fireEvent.click(anyone);
    expect(anyone).toHaveClass("bg-otter-50");
    expect(restricted).not.toHaveClass("bg-otter-50");
    expect(screen.getAllByText("Anyone with the link can view this file")).toHaveLength(2);

    fireEvent.click(restricted);
    expect(restricted).toHaveClass("bg-otter-50");
    fireEvent.click(screen.getByRole("button", { name: /People/ }));
    expect(screen.getByPlaceholderText("Add people by email")).toBeInTheDocument();
  });

  it("copies the file link and resets the Copied label", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /Get link/ }));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      fireEvent.click(screen.getByRole("button", { name: /Copy link/ }));
      expect(await screen.findByRole("button", { name: /Copied/ })).toBeInTheDocument();
      expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/files/file-123`);
      expect(toast.success).toHaveBeenCalledWith("Link copied to clipboard");
      await vi.advanceTimersByTimeAsync(2000);
      expect(await screen.findByRole("button", { name: /Copy link/ })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("reports clipboard failures", async () => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) } });
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /Get link/ }));
    fireEvent.click(screen.getByRole("button", { name: /Copy link/ }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Failed to copy link"));
    expect(within(screen.getByRole("button", { name: /Copy link/ })).queryByText("Copied")).not.toBeInTheDocument();
  });
});
