import { createRef } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it, vi } from "vitest";
import {
  FileUploadDropzone,
  MAX_UPLOAD_BYTES,
  type FileUploadDropzoneHandle,
} from "./file-upload-dropzone";

vi.mock("@/lib/native-notifications", () => ({
  notifyUploadComplete: vi.fn(),
  notifyUploadFailed: vi.fn(),
}));

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
  const addFiles = (files: File[]) => act(() => ref.current!.addFiles(files));
  return { addFiles, onUploadComplete };
}

function fileOf(name: string, size = 10): File {
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
  it("tracks progress per file and marks only the finished file done", async () => {
    const { uploadFile, calls } = controllableUpload();
    const { addFiles, onUploadComplete } = renderDropzone(uploadFile);

    addFiles([fileOf("a.txt"), fileOf("b.txt")]);
    expect(uploadFile).toHaveBeenCalledTimes(2);

    act(() => calls[0].options.onProgress(42));
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getAllByText("0%")).toHaveLength(1);

    await act(async () => calls[0].resolve());
    expect(screen.queryByText("42%")).not.toBeInTheDocument();
    expect(screen.getAllByTitle("Cancel upload")).toHaveLength(1);
    expect(onUploadComplete).toHaveBeenCalledTimes(1);
  });

  it("shows the failure banner and resets the entry on retry", async () => {
    const { uploadFile, calls } = controllableUpload();
    const { addFiles } = renderDropzone(uploadFile);

    addFiles([fileOf("a.txt")]);
    act(() => calls[0].options.onProgress(60));
    await act(async () => calls[0].reject(new Error("boom")));

    expect(screen.getByText("Upload failed")).toBeInTheDocument();
    expect(screen.getByText("File upload failed")).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Retry upload"));
    expect(uploadFile).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("Upload failed")).not.toBeInTheDocument();
    expect(screen.queryByText("File upload failed")).not.toBeInTheDocument();
    expect(screen.getByText("0%")).toBeInTheDocument();
  });

  it("reports a server 413 as a retryable size error", async () => {
    const { uploadFile, calls } = controllableUpload();
    const { addFiles } = renderDropzone(uploadFile);

    addFiles([fileOf("big.bin")]);
    await act(async () => calls[0].reject(axios413()));

    expect(screen.getByText("Server rejected this file as too large")).toBeInTheDocument();
    expect(screen.getByText(/File too large — limit is/)).toBeInTheDocument();
    expect(screen.queryByText("File upload failed")).not.toBeInTheDocument();
    expect(screen.getByTitle("Retry upload")).toBeInTheDocument();
  });

  it("removes a cancelled upload from the list", async () => {
    const { uploadFile, calls } = controllableUpload();
    const { addFiles } = renderDropzone(uploadFile);

    addFiles([fileOf("a.txt")]);
    fireEvent.click(screen.getByTitle("Cancel upload"));
    expect(calls[0].options.signal.aborted).toBe(true);
    await act(async () => calls[0].reject(new Error("aborted")));

    expect(screen.queryByText("a.txt")).not.toBeInTheDocument();
    expect(screen.queryByText("File upload failed")).not.toBeInTheDocument();
  });

  it("rejects oversized files client-side and lets the user remove them", () => {
    const { uploadFile } = controllableUpload();
    const { addFiles } = renderDropzone(uploadFile);

    addFiles([fileOf("huge.iso", MAX_UPLOAD_BYTES + 1)]);
    expect(uploadFile).not.toHaveBeenCalled();
    expect(screen.getByText(/File is too large/)).toBeInTheDocument();
    expect(screen.queryByTitle("Retry upload")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Remove file"));
    expect(screen.queryByText("huge.iso")).not.toBeInTheDocument();
  });
});
