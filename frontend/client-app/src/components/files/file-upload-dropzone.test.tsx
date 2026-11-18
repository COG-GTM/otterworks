import { createRef } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FileUploadDropzone, type FileUploadDropzoneHandle } from "./file-upload-dropzone";

vi.mock("@/lib/native-notifications", () => ({
  notifyUploadComplete: vi.fn(() => Promise.resolve()),
  notifyUploadFailed: vi.fn(() => Promise.resolve()),
}));

interface Deferred {
  resolve: () => void;
  reject: (err: unknown) => void;
}

function setup() {
  const pending = new Map<string, Deferred>();
  const uploadFile = vi.fn(
    (file: File) =>
      new Promise<void>((resolve, reject) => {
        pending.set(file.name, { resolve, reject });
      }),
  );
  const ref = createRef<FileUploadDropzoneHandle>();
  render(<FileUploadDropzone ref={ref} uploadFile={uploadFile} />);
  return { ref, pending };
}

function makeFiles(count: number): File[] {
  return Array.from({ length: count }, (_, i) => new File(["x"], `file-${i + 1}.txt`));
}

describe("FileUploadDropzone upload summary", () => {
  it("shows how many files finished out of the total, counting failures separately", async () => {
    const { ref, pending } = setup();

    act(() => ref.current!.addFiles(makeFiles(5)));
    expect(screen.getByTestId("upload-summary")).toHaveTextContent("0 of 5 uploaded");

    await act(async () => {
      pending.get("file-1.txt")!.resolve();
      pending.get("file-2.txt")!.resolve();
      pending.get("file-3.txt")!.resolve();
    });
    expect(screen.getByTestId("upload-summary")).toHaveTextContent(/^3 of 5 uploaded$/);

    await act(async () => {
      pending.get("file-4.txt")!.reject(new Error("network"));
    });
    expect(screen.getByTestId("upload-summary")).toHaveTextContent("3 of 5 uploaded, 1 failed");
  });

  it("Clear completed removes finished uploads and keeps in-progress and failed ones", async () => {
    const { ref, pending } = setup();

    act(() => ref.current!.addFiles(makeFiles(4)));
    const clearButton = screen.getByRole("button", { name: "Clear completed" });
    expect(clearButton).toBeDisabled();

    await act(async () => {
      pending.get("file-1.txt")!.resolve();
      pending.get("file-2.txt")!.resolve();
      pending.get("file-3.txt")!.reject(new Error("network"));
    });
    expect(clearButton).toBeEnabled();

    fireEvent.click(clearButton);

    expect(screen.queryByText("file-1.txt")).not.toBeInTheDocument();
    expect(screen.queryByText("file-2.txt")).not.toBeInTheDocument();
    expect(screen.getByText("file-3.txt")).toBeInTheDocument();
    expect(screen.getByText("file-4.txt")).toBeInTheDocument();
    expect(screen.getByTestId("upload-summary")).toHaveTextContent("0 of 2 uploaded, 1 failed");
    expect(screen.getByRole("button", { name: "Clear completed" })).toBeDisabled();
  });
});
