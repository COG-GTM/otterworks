import { createRef } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it, vi } from "vitest";
import { FileUploadDropzone, MAX_UPLOAD_BYTES } from "./file-upload-dropzone";
import type { FileUploadDropzoneHandle } from "./file-upload-dropzone";

type UploadOptions = { onProgress: (percent: number) => void; signal: AbortSignal };

interface PendingUpload {
  options: UploadOptions;
  resolve: () => void;
  reject: (err: unknown) => void;
}

function controllableUpload() {
  const calls: PendingUpload[] = [];
  const uploadFile = vi.fn(
    (_file: File, options: UploadOptions) =>
      new Promise<void>((resolve, reject) => {
        calls.push({ options, resolve, reject });
      }),
  );
  return { uploadFile, calls };
}

function renderDropzone(uploadFile: ReturnType<typeof controllableUpload>["uploadFile"]) {
  const ref = createRef<FileUploadDropzoneHandle>();
  const onUploadComplete = vi.fn();
  render(<FileUploadDropzone ref={ref} uploadFile={uploadFile} onUploadComplete={onUploadComplete} />);
  const add = (file: File) => act(() => ref.current!.addFiles([file]));
  return { add, onUploadComplete };
}

function axios413() {
  return new AxiosError("too large", "ERR_BAD_REQUEST", undefined, undefined, {
    status: 413,
    statusText: "Payload Too Large",
    headers: {},
    config: { headers: new AxiosHeaders() },
    data: null,
  });
}

describe("FileUploadDropzone upload lifecycle", () => {
  it("reports progress and marks the file done on success", async () => {
    const { uploadFile, calls } = controllableUpload();
    const { add, onUploadComplete } = renderDropzone(uploadFile);
    add(new File(["hello"], "a.txt"));

    act(() => calls[0].options.onProgress(42));
    expect(screen.getByText("42%")).toBeInTheDocument();

    await act(async () => calls[0].resolve());
    expect(screen.queryByText("42%")).not.toBeInTheDocument();
    expect(screen.getByText(/Upload complete/)).toBeInTheDocument();
    expect(onUploadComplete).toHaveBeenCalledTimes(1);
  });

  it("shows the failure banner and retries a failed upload", async () => {
    const { uploadFile, calls } = controllableUpload();
    renderDropzone(uploadFile).add(new File(["x"], "b.txt"));

    await act(async () => calls[0].reject(new Error("boom")));
    expect(screen.getByText("Upload failed")).toBeInTheDocument();
    expect(screen.getByText("File upload failed")).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Retry upload"));
    expect(uploadFile).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("Upload failed")).not.toBeInTheDocument();
    expect(screen.getByText("0%")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("File upload failed")).not.toBeInTheDocument());
  });

  it("treats a server 413 as a size rejection, not an upload failure", async () => {
    const { uploadFile, calls } = controllableUpload();
    renderDropzone(uploadFile).add(new File(["x"], "c.bin"));

    await act(async () => calls[0].reject(axios413()));
    expect(screen.getByText("Server rejected this file as too large")).toBeInTheDocument();
    expect(screen.getByText(/File too large/)).toBeInTheDocument();
    expect(screen.queryByText("File upload failed")).not.toBeInTheDocument();
    expect(screen.getByTitle("Retry upload")).toBeInTheDocument();
  });

  it("removes a cancelled upload without reporting an error", async () => {
    const { uploadFile, calls } = controllableUpload();
    renderDropzone(uploadFile).add(new File(["x"], "d.txt"));

    fireEvent.click(screen.getByTitle("Cancel upload"));
    expect(calls[0].options.signal.aborted).toBe(true);
    await act(async () => calls[0].reject(new Error("aborted")));
    expect(screen.queryByText("d.txt")).not.toBeInTheDocument();
    expect(screen.queryByText("File upload failed")).not.toBeInTheDocument();
  });

  it("rejects oversized files client-side and lets the user remove them", () => {
    const { uploadFile } = controllableUpload();
    const big = new File(["x"], "huge.iso");
    Object.defineProperty(big, "size", { value: MAX_UPLOAD_BYTES + 1 });
    renderDropzone(uploadFile).add(big);

    expect(uploadFile).not.toHaveBeenCalled();
    expect(screen.getByText(/File is too large/)).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Remove file"));
    expect(screen.queryByText("huge.iso")).not.toBeInTheDocument();
  });
});
