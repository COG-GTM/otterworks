import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { ChevronLeft, ChevronRight, Download, ExternalLink, X } from "lucide-react";
import type { FileItem } from "@/types";
import { filesApi } from "@/lib/api";
import { formatFileSize } from "@/lib/utils";
import { FilePreview } from "@/components/files/file-preview";

interface FilePreviewModalProps {
  /** Files the user can step through with the arrow keys / buttons. */
  files: FileItem[];
  fileId: string;
  onClose: () => void;
}

export function FilePreviewModal({ files, fileId, onClose }: FilePreviewModalProps) {
  const previewable = files.filter((f) => !f.isFolder);
  const [currentId, setCurrentId] = useState(fileId);
  const index = previewable.findIndex((f) => f.id === currentId);
  const file = index >= 0 ? previewable[index] : undefined;
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => setCurrentId(fileId), [fileId]);

  const { data: previewUrl, isLoading: isUrlLoading } = useQuery({
    queryKey: ["files", currentId, "preview-url"],
    queryFn: () => filesApi.getPreviewUrl(currentId),
    enabled: !!file,
    staleTime: 30 * 60 * 1000,
  });

  const step = useCallback(
    (delta: number) => {
      if (previewable.length < 2 || index < 0) return;
      const next = (index + delta + previewable.length) % previewable.length;
      setCurrentId(previewable[next].id);
    },
    [index, previewable],
  );

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      // Let focused media/form controls keep arrow keys (e.g. seeking).
      const target = e.target as HTMLElement | null;
      if (
        target?.isContentEditable ||
        target?.closest("video, audio, input, textarea, select")
      ) {
        return;
      }
      if (e.key === "ArrowRight") step(1);
      else if (e.key === "ArrowLeft") step(-1);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose, step]);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  const handleDownload = useCallback(async () => {
    if (!file) return;
    try {
      const url = await filesApi.getDownloadUrl(file.id);
      const a = document.createElement("a");
      a.href = url;
      a.download = file.name;
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      a.remove();
      toast.success(`Downloading ${file.name}`);
    } catch {
      toast.error("Download failed. Please try again.");
    }
  }, [file]);

  if (!file) return null;

  const canStep = previewable.length > 1;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="file-preview-title"
    >
      <div className="fixed inset-0 bg-black/60" onClick={onClose} aria-hidden="true" />

      {canStep && (
        <button
          onClick={() => step(-1)}
          className="relative z-10 hidden sm:flex mr-3 p-2 rounded-full bg-white/90 text-gray-700 hover:bg-white shadow"
          aria-label="Previous file"
        >
          <ChevronLeft size={20} />
        </button>
      )}

      <div className="relative z-10 flex flex-col bg-white rounded-xl shadow-2xl w-full max-w-5xl max-h-[90vh]">
        <div className="flex items-center justify-between gap-4 px-5 py-3 border-b border-gray-200">
          <div className="min-w-0">
            <h2 id="file-preview-title" className="text-sm font-semibold text-gray-900 truncate">
              {file.name}
            </h2>
            <p className="text-xs text-gray-500 truncate">
              {formatFileSize(file.size)} &middot; {file.mimeType || "Unknown type"}
              {canStep && ` \u00b7 ${index + 1} of ${previewable.length}`}
            </p>
          </div>
          <div className="flex items-center gap-1 flex-shrink-0">
            <Link
              to={`/files/${file.id}`}
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-sm text-gray-700 rounded-lg hover:bg-gray-100"
            >
              <ExternalLink size={16} />
              <span className="hidden sm:inline">Details</span>
            </Link>
            <button
              onClick={handleDownload}
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-sm text-gray-700 rounded-lg hover:bg-gray-100"
            >
              <Download size={16} />
              <span className="hidden sm:inline">Download</span>
            </button>
            <button
              ref={closeRef}
              onClick={onClose}
              className="p-1.5 rounded-lg text-gray-500 hover:bg-gray-100"
              aria-label="Close preview"
            >
              <X size={18} />
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-auto p-6 flex items-center justify-center min-h-[300px] bg-gray-50 rounded-b-xl">
          <FilePreview
            key={file.id}
            fileName={file.name}
            mimeType={file.mimeType}
            presignedUrl={previewUrl}
            isUrlLoading={isUrlLoading}
            onDownload={handleDownload}
          />
        </div>
      </div>

      {canStep && (
        <button
          onClick={() => step(1)}
          className="relative z-10 hidden sm:flex ml-3 p-2 rounded-full bg-white/90 text-gray-700 hover:bg-white shadow"
          aria-label="Next file"
        >
          <ChevronRight size={20} />
        </button>
      )}
    </div>
  );
}
