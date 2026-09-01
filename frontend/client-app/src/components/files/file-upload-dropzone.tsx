import { useCallback, useState, useRef, useEffect, useImperativeHandle, forwardRef } from "react";
import type { Ref } from "react";
import { useDropzone } from "react-dropzone";
import { isAxiosError } from "axios";
import { Upload, X, FileIcon, CheckCircle2, AlertCircle, RotateCcw } from "lucide-react";
import { cn, formatFileSize } from "@/lib/utils";
import { notifyUploadComplete, notifyUploadFailed } from "@/lib/native-notifications";
import { ChaosErrorBanner } from "@/components/chaos/chaos-error-banner";

interface FileUploadDropzoneProps {
  uploadFile: (
    file: File,
    options: { onProgress: (percent: number) => void; signal: AbortSignal },
  ) => Promise<void>;
  onUploadComplete?: () => void;
  onDismiss?: () => void;
  className?: string;
}

export interface FileUploadDropzoneHandle {
  addFiles: (files: File[]) => void;
}

interface UploadingFile {
  id: string;
  file: File;
  progress: number;
  status: "uploading" | "done" | "error";
  error?: string;
  /** Rejected for size: retrying can never succeed. */
  tooLarge?: boolean;
  /** Distinguishes a size rejection from a genuine upload failure. */
  errorKind?: "size" | "failure";
  abortController?: AbortController;
}

/** Mirrors file-service's MAX_UPLOAD_BYTES and the nginx body limits in front of it. */
export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;

const TOO_LARGE_ERROR = `File is too large — the limit is ${formatFileSize(MAX_UPLOAD_BYTES)}`;

/**
 * Only reachable for files under the client limit — a proxy hop with a smaller
 * body limit than file-service. Retry stays available.
 */
const SERVER_TOO_LARGE_ERROR = "Server rejected this file as too large";

function isTooLargeError(err: unknown): boolean {
  return isAxiosError(err) && err.response?.status === 413;
}

let fileIdCounter = 0;

export const FileUploadDropzone = forwardRef(function FileUploadDropzone(
  { uploadFile, onUploadComplete, onDismiss, className }: FileUploadDropzoneProps,
  ref: Ref<FileUploadDropzoneHandle>,
) {
  const [uploadingFiles, setUploadingFiles] = useState<UploadingFile[]>([]);
  const [showUploadErrorBanner, setShowUploadErrorBanner] = useState(false);
  const [showTooLargeBanner, setShowTooLargeBanner] = useState(false);
  const [dismissing, setDismissing] = useState(false);
  const dismissTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onDismissRef = useRef(onDismiss);

  useEffect(() => {
    onDismissRef.current = onDismiss;
  }, [onDismiss]);

  useEffect(() => {
    if (uploadingFiles.length === 0) {
      setDismissing(false);
      setShowUploadErrorBanner(false);
      setShowTooLargeBanner(false);
      return;
    }
    const allDone = uploadingFiles.every((f) => f.status === "done");
    const hasUploading = uploadingFiles.some((f) => f.status === "uploading");

    if (!uploadingFiles.some((f) => f.status === "error" && f.errorKind === "failure")) {
      setShowUploadErrorBanner(false);
    }
    if (!uploadingFiles.some((f) => f.status === "error" && f.errorKind === "size")) {
      setShowTooLargeBanner(false);
    }

    if (allDone && !hasUploading) {
      setDismissing(true);
      dismissTimerRef.current = setTimeout(() => {
        setUploadingFiles([]);
        setDismissing(false);
        onDismissRef.current?.();
      }, 3000);
    } else {
      setDismissing(false);
      if (dismissTimerRef.current) {
        clearTimeout(dismissTimerRef.current);
        dismissTimerRef.current = null;
      }
    }

    return () => {
      if (dismissTimerRef.current) {
        clearTimeout(dismissTimerRef.current);
      }
    };
  }, [uploadingFiles]);

  const startUpload = useCallback(
    (entry: UploadingFile) => {
      setShowUploadErrorBanner(false);
      const abortController = new AbortController();

      setUploadingFiles((prev) =>
        prev.map((f) =>
          f.id === entry.id
            ? {
                ...f,
                status: "uploading" as const,
                progress: 0,
                error: undefined,
                errorKind: undefined,
                abortController,
              }
            : f,
        ),
      );

      uploadFile(entry.file, {
        onProgress: (percent) => {
          setUploadingFiles((prev) =>
            prev.map((f) => (f.id === entry.id ? { ...f, progress: percent } : f)),
          );
        },
        signal: abortController.signal,
      })
        .then(() => {
          setUploadingFiles((prev) =>
            prev.map((f) =>
              f.id === entry.id
                ? { ...f, status: "done" as const, progress: 100, abortController: undefined }
                : f,
            ),
          );
          void notifyUploadComplete(entry.file.name);
          onUploadComplete?.();
        })
        .catch((err: unknown) => {
          if (abortController.signal.aborted) {
            setUploadingFiles((prev) => prev.filter((f) => f.id !== entry.id));
          } else {
            const rejectedTooLarge = isTooLargeError(err);
            setUploadingFiles((prev) =>
              prev.map((f) =>
                f.id === entry.id
                  ? {
                      ...f,
                      status: "error" as const,
                      error: rejectedTooLarge ? SERVER_TOO_LARGE_ERROR : "Upload failed",
                      errorKind: rejectedTooLarge ? ("size" as const) : ("failure" as const),
                      abortController: undefined,
                    }
                  : f,
              ),
            );
            if (rejectedTooLarge) {
              setShowTooLargeBanner(true);
            } else {
              setShowUploadErrorBanner(true);
            }
            void notifyUploadFailed(entry.file.name);
          }
        });
    },
    [uploadFile, onUploadComplete],
  );

  const addFiles = useCallback(
    (files: File[]) => {
      const newFiles: UploadingFile[] = files.map((file) => {
        const tooLarge = file.size > MAX_UPLOAD_BYTES;
        return {
          id: `upload-${++fileIdCounter}`,
          file,
          progress: 0,
          status: tooLarge ? ("error" as const) : ("uploading" as const),
          error: tooLarge ? TOO_LARGE_ERROR : undefined,
          errorKind: tooLarge ? ("size" as const) : undefined,
          tooLarge,
        };
      });
      setUploadingFiles((prev) => [...prev, ...newFiles]);
      if (newFiles.some((entry) => entry.tooLarge)) {
        setShowTooLargeBanner(true);
      }
      newFiles.forEach((entry) => {
        if (entry.tooLarge) {
          void notifyUploadFailed(entry.file.name);
        } else {
          startUpload(entry);
        }
      });
    },
    [startUpload],
  );

  useImperativeHandle(ref, () => ({ addFiles }), [addFiles]);

  const cancelUpload = (id: string) => {
    const entry = uploadingFiles.find((f) => f.id === id);
    entry?.abortController?.abort();
  };

  const retryUpload = (id: string) => {
    const entry = uploadingFiles.find((f) => f.id === id);
    if (entry && !entry.tooLarge) startUpload(entry);
  };

  const removeUpload = (id: string) => {
    setUploadingFiles((prev) => prev.filter((f) => f.id !== id));
  };

  const clearCompleted = () => {
    setUploadingFiles((prev) => prev.filter((f) => f.status === "uploading"));
  };

  const dismissErrorBanner = () => {
    setShowUploadErrorBanner(false);
  };

  const dismissTooLargeBanner = () => {
    setShowTooLargeBanner(false);
  };

  const oversizedNames = uploadingFiles
    .filter((f) => f.status === "error" && f.errorKind === "size")
    .map((f) => f.file.name);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop: addFiles,
    multiple: true,
  });

  return (
    <div className={className}>
      {showTooLargeBanner && oversizedNames.length > 0 && (
        <ChaosErrorBanner
          className="mb-4"
          variant="warning"
          title={`File too large — limit is ${formatFileSize(MAX_UPLOAD_BYTES)}`}
          message={`${
            oversizedNames.length === 1
              ? `"${oversizedNames[0]}" exceeds`
              : `${oversizedNames.length} files exceed`
          } the ${formatFileSize(MAX_UPLOAD_BYTES)} per-file limit. Nothing is wrong with the upload service — please pick a smaller file and try again.`}
          onDismiss={dismissTooLargeBanner}
        />
      )}
      {showUploadErrorBanner && (
        <ChaosErrorBanner
          className="mb-4"
          title="File upload failed"
          message="One or more files could not be uploaded. Please try again."
          onDismiss={dismissErrorBanner}
        />
      )}
      <div
        {...getRootProps()}
        className={cn(
          "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition",
          isDragActive
            ? "border-otter-500 bg-otter-50"
            : "border-gray-300 hover:border-otter-400 hover:bg-gray-50",
        )}
      >
        <input {...getInputProps()} />
        <Upload
          size={32}
          className={cn(
            "mx-auto mb-3",
            isDragActive ? "text-otter-600" : "text-gray-400",
          )}
        />
        {isDragActive ? (
          <p className="text-sm text-otter-600 font-medium">Drop files here</p>
        ) : (
          <>
            <p className="text-sm text-gray-600 font-medium">
              Drag & drop files here, or click to browse
            </p>
            <p className="text-xs text-gray-400 mt-1">
              Any file type, up to 100MB per file
            </p>
          </>
        )}
      </div>

      {uploadingFiles.length > 0 && (
        <div className="mt-4 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-gray-700">
              {dismissing ? (
                <span className="flex items-center gap-1.5 text-green-600">
                  <CheckCircle2 size={14} />
                  Upload complete — closing shortly
                </span>
              ) : (
                "Uploads"
              )}
            </p>
            {!dismissing && (
              <button
                onClick={clearCompleted}
                className="text-xs text-gray-500 hover:text-gray-700"
              >
                Clear completed
              </button>
            )}
          </div>
          {uploadingFiles.map((item) => (
            <div
              key={item.id}
              className="flex items-center gap-3 p-2 bg-white rounded-lg border border-gray-200"
            >
              <FileIcon size={16} className="text-gray-400 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-gray-700 truncate">{item.file.name}</p>
                <div className="flex items-center gap-2">
                  <p className="text-xs text-gray-400">{formatFileSize(item.file.size)}</p>
                  {item.status === "uploading" && (
                    <p className="text-xs text-otter-600 font-medium">{item.progress}%</p>
                  )}
                </div>
                {item.status === "uploading" && (
                  <div className="mt-1 h-1.5 w-full bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-otter-500 rounded-full transition-all duration-300"
                      style={{ width: `${item.progress}%` }}
                    />
                  </div>
                )}
                {item.status === "error" && (
                  <p className="text-xs text-red-500 mt-0.5">{item.error}</p>
                )}
              </div>
              {item.status === "done" && (
                <CheckCircle2 size={16} className="text-green-500 flex-shrink-0" />
              )}
              {item.status === "error" && (
                <div className="flex items-center gap-1 flex-shrink-0">
                  {item.tooLarge ? (
                    <button
                      onClick={() => removeUpload(item.id)}
                      className="p-1 text-gray-400 hover:text-red-500 transition"
                      title="Remove file"
                    >
                      <X size={14} />
                    </button>
                  ) : (
                    <button
                      onClick={() => retryUpload(item.id)}
                      className="p-1 text-gray-400 hover:text-otter-600 transition"
                      title="Retry upload"
                    >
                      <RotateCcw size={14} />
                    </button>
                  )}
                  <AlertCircle size={16} className="text-red-500" />
                </div>
              )}
              {item.status === "uploading" && (
                <button
                  onClick={() => cancelUpload(item.id)}
                  className="p-1 text-gray-400 hover:text-red-500 transition flex-shrink-0"
                  title="Cancel upload"
                >
                  <X size={14} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
});
