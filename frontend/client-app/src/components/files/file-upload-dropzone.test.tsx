import { createRef } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

function setup() {
  const pending: PendingUpload[] = [];
  const uploadFile = vi.fn(
    (_file: File, options: UploadOptions) =>
      new Promise<void>((resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(new Error("aborted")));
        pending.push({ options, resolve, reject });
      }),
  );
  const onUploadComplete = vi.fn();
  const ref = createRef<FileUploadDropzoneHandle>();
  render(
    <FileUploadDropzone ref={ref} uploadFile={uploadFile} onUploadComplete={onUploadComplete} />,
  );
  const add = (...files: File[]) => act(() => ref.current!.addFiles(files));
  return { pending, uploadFile, onUploadComplete, add };
}

function file(name: string, size = 10) {
  const f = new File(["x"], name);
  Object.defineProperty(f, "size", { value: size });
  return f;
}

function tooLargeError() {
  const headers = new AxiosHeaders();
  return new AxiosError("413", "ERR_BAD_REQUEST", undefined, undefined, {
    status: 413,
    statusText: "Payload Too Large",
    headers,
    config: { headers },
    data: null,
  });
}

describe("FileUploadDropzone upload state", () => {
  it("tracks progress and marks only the finished entry as done", async () => {
    const { pending, onUploadComplete, add } = setup();
    add(file("a.txt"), file("b.txt"));
    expect(screen.getAllByText("0%")).toHaveLength(2);

    act(() => pending[0].options.onProgress(42));
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByText("0%")).toBeInTheDocument();

    await act(async () => pending[0].resolve());
    expect(screen.queryByText("42%")).not.toBeInTheDocument();
    expect(screen.getByText("0%")).toBeInTheDocument();
    expect(onUploadComplete).toHaveBeenCalledTimes(1);
  });

  it("removes a cancelled upload from the list", async () => {
    const { add } = setup();
    add(file("cancel-me.txt"));
    fireEvent.click(screen.getByTitle("Cancel upload"));
    await waitFor(() => expect(screen.queryByText("cancel-me.txt")).not.toBeInTheDocument());
  });

  it("shows a failure, then resets progress and status on retry", async () => {
    const { pending, uploadFile, add } = setup();
    add(file("flaky.txt"));
    act(() => pending[0].options.onProgress(60));
    await act(async () => pending[0].reject(new Error("boom")));

    expect(screen.getByText("Upload failed")).toBeInTheDocument();
    expect(screen.getByText("File upload failed")).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Retry upload"));
    expect(uploadFile).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("Upload failed")).not.toBeInTheDocument();
    expect(screen.queryByText("File upload failed")).not.toBeInTheDocument();
    expect(screen.getByText("0%")).toBeInTheDocument();
  });

  it("reports a server 413 as a size error with retry still available", async () => {
    const { pending, add } = setup();
    add(file("big-ish.bin"));
    await act(async () => pending[0].reject(tooLargeError()));

    expect(screen.getByText("Server rejected this file as too large")).toBeInTheDocument();
    expect(screen.getByText(/File too large/)).toBeInTheDocument();
    expect(screen.queryByText("File upload failed")).not.toBeInTheDocument();
    expect(screen.getByTitle("Retry upload")).toBeInTheDocument();
  });

  it("rejects oversized files client-side and lets the user remove them", () => {
    const { uploadFile, add } = setup();
    add(file("huge.iso", MAX_UPLOAD_BYTES + 1));

    expect(uploadFile).not.toHaveBeenCalled();
    expect(screen.getByText(/File too large/)).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Remove file"));
    expect(screen.queryByText("huge.iso")).not.toBeInTheDocument();
  });
});
