import { createRef } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it, vi } from "vitest";
import {
  FileUploadDropzone,
  MAX_UPLOAD_BYTES,
  type FileUploadDropzoneHandle,
} from "./file-upload-dropzone";

type UploadFn = React.ComponentProps<typeof FileUploadDropzone>["uploadFile"];

interface PendingUpload {
  onProgress: (percent: number) => void;
  signal: AbortSignal;
  resolve: () => void;
  reject: (err: unknown) => void;
}

function controllableUpload() {
  const calls: PendingUpload[] = [];
  const uploadFile = vi.fn<UploadFn>(
    (_file, { onProgress, signal }) =>
      new Promise<void>((resolve, reject) => {
        calls.push({ onProgress, signal, resolve, reject });
      }),
  );
  return { uploadFile, calls };
}

function renderDropzone(uploadFile: UploadFn, onUploadComplete = vi.fn()) {
  const ref = createRef<FileUploadDropzoneHandle>();
  render(
    <FileUploadDropzone ref={ref} uploadFile={uploadFile} onUploadComplete={onUploadComplete} />,
  );
  const addFiles = (files: File[]) => act(() => ref.current!.addFiles(files));
  return { addFiles, onUploadComplete };
}

function sized(name: string, size: number): File {
  const file = new File(["x"], name);
  Object.defineProperty(file, "size", { value: size });
  return file;
}

function axios413(): AxiosError {
  const headers = new AxiosHeaders();
  return new AxiosError("too large", "ERR_BAD_REQUEST", undefined, undefined, {
    status: 413,
    statusText: "Payload Too Large",
    headers,
    config: { headers },
    data: null,
  });
}

describe("FileUploadDropzone", () => {
  it("tracks progress and marks the upload done", async () => {
    const { uploadFile, calls } = controllableUpload();
    const { addFiles, onUploadComplete } = renderDropzone(uploadFile);

    addFiles([new File(["hello"], "a.txt")]);
    expect(screen.getByText("0%")).toBeInTheDocument();

    act(() => calls[0].onProgress(42));
    expect(screen.getByText("42%")).toBeInTheDocument();

    await act(async () => calls[0].resolve());
    expect(screen.queryByText("42%")).not.toBeInTheDocument();
    expect(screen.getByText(/Upload complete/)).toBeInTheDocument();
    expect(onUploadComplete).toHaveBeenCalledTimes(1);
  });

  it("shows a retryable failure and resets the entry on retry", async () => {
    const { uploadFile, calls } = controllableUpload();
    const { addFiles } = renderDropzone(uploadFile);

    addFiles([new File(["hello"], "a.txt")]);
    act(() => calls[0].onProgress(30));
    await act(async () => calls[0].reject(new Error("boom")));

    expect(screen.getByText("Upload failed")).toBeInTheDocument();
    expect(screen.getByText("File upload failed")).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Retry upload"));
    expect(uploadFile).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("Upload failed")).not.toBeInTheDocument();
    expect(screen.queryByText("File upload failed")).not.toBeInTheDocument();
    expect(screen.getByText("0%")).toBeInTheDocument();
  });

  it("labels a server 413 as a size rejection, not a failure", async () => {
    const { uploadFile, calls } = controllableUpload();
    const { addFiles } = renderDropzone(uploadFile);

    addFiles([new File(["hello"], "a.txt")]);
    await act(async () => calls[0].reject(axios413()));

    expect(screen.getByText("Server rejected this file as too large")).toBeInTheDocument();
    expect(screen.getByText(/^File too large/)).toBeInTheDocument();
    expect(screen.queryByText("File upload failed")).not.toBeInTheDocument();
    expect(screen.getByTitle("Retry upload")).toBeInTheDocument();
  });

  it("removes a cancelled upload from the list", async () => {
    const { uploadFile, calls } = controllableUpload();
    const { addFiles } = renderDropzone(uploadFile);

    addFiles([new File(["hello"], "a.txt"), new File(["world"], "b.txt")]);
    fireEvent.click(screen.getAllByTitle("Cancel upload")[0]);
    expect(calls[0].signal.aborted).toBe(true);
    await act(async () => calls[0].reject(new Error("aborted")));

    expect(screen.queryByText("a.txt")).not.toBeInTheDocument();
    expect(screen.getByText("b.txt")).toBeInTheDocument();
    expect(screen.queryByText("File upload failed")).not.toBeInTheDocument();
  });

  it("rejects oversized files client-side without uploading", () => {
    const { uploadFile } = controllableUpload();
    const { addFiles } = renderDropzone(uploadFile);

    addFiles([sized("big.bin", MAX_UPLOAD_BYTES + 1)]);
    expect(uploadFile).not.toHaveBeenCalled();
    expect(screen.getByText(/File is too large/)).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Remove file"));
    expect(screen.queryByText("big.bin")).not.toBeInTheDocument();
  });
});
