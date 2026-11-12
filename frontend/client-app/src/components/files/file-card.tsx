import { Link } from "react-router-dom";
import {
  File,
  FileText,
  Folder,
  Image,
  Film,
  Music,
  Archive,
  Table,
  MoreVertical,
  Trash2,
  Share2,
  Download,
  Pencil,
  Check,
  X,
  Star,
} from "lucide-react";
import { useState, useRef, useEffect, useCallback } from "react";
import type { FileItem } from "@/types";
import { formatFileSize, formatRelativeTime } from "@/lib/utils";
import { starredApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";

const iconMap: Record<string, typeof File> = {
  file: File,
  "file-text": FileText,
  image: Image,
  video: Film,
  music: Music,
  archive: Archive,
  table: Table,
};

function getIconComponent(mimeType: string) {
  if (mimeType.startsWith("image/")) return Image;
  if (mimeType.startsWith("video/")) return Film;
  if (mimeType.startsWith("audio/")) return Music;
  if (mimeType === "application/pdf") return FileText;
  if (mimeType.includes("spreadsheet") || mimeType.includes("excel")) return Table;
  if (mimeType.includes("zip") || mimeType.includes("archive")) return Archive;
  if (mimeType.includes("document") || mimeType.includes("word")) return FileText;
  return File;
}

interface FileCardProps {
  file: FileItem;
  onDelete?: (id: string) => void;
  onShare?: (id: string) => void;
  onRename?: (id: string, name: string) => void;
  onDownload?: (id: string, name: string) => void;
  view?: "grid" | "list";
  selected?: boolean;
  onSelect?: (id: string) => void;
  selectionActive?: boolean;
  onStarToggle?: () => void;
}

function fileHref(file: FileItem) {
  return file.isFolder ? `/files?folder=${file.id}` : `/files/${file.id}`;
}

function SelectionCheckbox({
  selected,
  className,
  onClick,
}: {
  selected: boolean;
  className: string;
  onClick: (e: React.MouseEvent) => void;
}) {
  return (
    <div className={className} onClick={onClick}>
      <input
        type="checkbox"
        checked={selected}
        readOnly
        className="h-4 w-4 rounded border-gray-300 text-otter-600 focus:ring-otter-500 cursor-pointer"
      />
    </div>
  );
}

function StarButton({
  starred,
  className,
  onClick,
}: {
  starred: boolean;
  className: string;
  onClick: (e: React.MouseEvent) => void;
}) {
  return (
    <button onClick={onClick} className={className} aria-label={starred ? "Unstar" : "Star"}>
      <Star
        size={16}
        className={starred ? "text-yellow-400 fill-yellow-400" : "text-gray-400 opacity-0 group-hover:opacity-100"}
      />
    </button>
  );
}

function RenameInput({
  inputRef,
  value,
  onChange,
  onSubmit,
  onCancel,
}: {
  inputRef: React.RefObject<HTMLInputElement>;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") onSubmit();
    if (e.key === "Escape") onCancel();
  };

  return (
    <input
      ref={inputRef}
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={handleKeyDown}
      onBlur={onSubmit}
      className="text-sm font-medium text-gray-900 px-1 py-0.5 border border-otter-400 rounded focus:outline-none focus:ring-1 focus:ring-otter-500 w-full"
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}
    />
  );
}

function FileMenuTrigger({
  file,
  wrapperClassName,
  buttonClassName,
  onDelete,
  onShare,
  onRename,
  onDownload,
}: {
  file: FileItem;
  wrapperClassName: string;
  buttonClassName: string;
  onDelete?: (id: string) => void;
  onShare?: (id: string) => void;
  onRename: () => void;
  onDownload?: (id: string, name: string) => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className={wrapperClassName}>
      <button
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setMenuOpen(!menuOpen);
        }}
        className={buttonClassName}
      >
        <MoreVertical size={16} />
      </button>
      {menuOpen && (
        <FileMenu
          file={file}
          onClose={() => setMenuOpen(false)}
          onDelete={onDelete}
          onShare={onShare}
          onRename={onRename}
          onDownload={onDownload}
        />
      )}
    </div>
  );
}

function useStarred(file: FileItem, onStarToggle?: () => void) {
  const { user } = useAuthStore();
  const userId = user?.id ?? "";
  const [starred, setStarred] = useState(() => userId ? starredApi.isStarred(userId, file.id) : false);

  useEffect(() => {
    if (userId) {
      setStarred(starredApi.isStarred(userId, file.id));
    }
  }, [userId, file.id]);

  const handleStarClick = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!userId) return;
    const nowStarred = starredApi.toggle(userId, file.id, file.isFolder ? "folder" : "file");
    setStarred(nowStarred);
    onStarToggle?.();
  }, [userId, file.id, file.isFolder, onStarToggle]);

  return { starred, handleStarClick };
}

function useRename(file: FileItem, onRename?: (id: string, name: string) => void) {
  const [isRenaming, setIsRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState(file.name);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const renameDoneRef = useRef(false);

  useEffect(() => {
    if (isRenaming && renameInputRef.current) {
      renameInputRef.current.focus();
      const dotIdx = file.name.lastIndexOf(".");
      renameInputRef.current.setSelectionRange(0, dotIdx > 0 ? dotIdx : file.name.length);
    }
  }, [isRenaming, file.name]);

  const startRename = () => {
    renameDoneRef.current = false;
    setIsRenaming(true);
    setRenameValue(file.name);
  };

  const submitRename = () => {
    if (renameDoneRef.current) return;
    renameDoneRef.current = true;
    const trimmed = renameValue.trim();
    if (trimmed && trimmed !== file.name) {
      onRename?.(file.id, trimmed);
    }
    setIsRenaming(false);
  };

  const cancelRename = () => {
    renameDoneRef.current = true;
    setIsRenaming(false);
    setRenameValue(file.name);
  };

  return {
    isRenaming,
    renameValue,
    setRenameValue,
    renameInputRef,
    startRename,
    submitRename,
    cancelRename,
  };
}

export function FileCard({
  file,
  onDelete,
  onShare,
  onRename,
  onDownload,
  view = "grid",
  selected = false,
  onSelect,
  selectionActive = false,
  onStarToggle,
}: FileCardProps) {
  const { starred, handleStarClick } = useStarred(file, onStarToggle);
  const rename = useRename(file, onRename);
  const Icon = file.isFolder ? Folder : getIconComponent(file.mimeType);

  const handleCheckboxClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onSelect?.(file.id);
  };

  const renameInput = (
    <RenameInput
      inputRef={rename.renameInputRef}
      value={rename.renameValue}
      onChange={rename.setRenameValue}
      onSubmit={rename.submitRename}
      onCancel={rename.cancelRename}
    />
  );

  if (view === "list") {
    return (
      <div className="flex items-center gap-4 px-4 py-2.5 hover:bg-gray-50 rounded-lg transition group border-b border-gray-100 last:border-0">
        {selectionActive && (
          <SelectionCheckbox selected={selected} className="flex-shrink-0" onClick={handleCheckboxClick} />
        )}
        <Link to={fileHref(file)} className="flex items-center gap-4 flex-1 min-w-0">
          <div className="w-10 h-10 rounded-lg bg-otter-50 flex items-center justify-center flex-shrink-0">
            <Icon size={20} className="text-otter-600" />
          </div>
          <div className="flex-1 min-w-0">
            {rename.isRenaming ? (
              <div className="flex items-center gap-1" onClick={(e) => e.preventDefault()}>
                {renameInput}
              </div>
            ) : (
              <p className="text-sm font-medium text-gray-900 truncate">{file.name}</p>
            )}
          </div>
          <span className="text-xs text-gray-500 w-32 hidden sm:block truncate">
            {formatRelativeTime(file.updatedAt)}
          </span>
          <span className="text-xs text-gray-400 w-20 hidden sm:block text-right">
            {file.isFolder ? "\u2014" : formatFileSize(file.size)}
          </span>
        </Link>
        <StarButton
          starred={starred}
          className="p-1 rounded hover:bg-gray-200 transition flex-shrink-0"
          onClick={handleStarClick}
        />
        <FileMenuTrigger
          file={file}
          wrapperClassName="relative w-8"
          buttonClassName="p-1 rounded hover:bg-gray-200 text-gray-400 opacity-0 group-hover:opacity-100 transition"
          onDelete={onDelete}
          onShare={onShare}
          onRename={rename.startRename}
          onDownload={onDownload}
        />
      </div>
    );
  }

  return (
    <div className="group relative flex flex-col rounded-xl border border-gray-200 bg-white hover:shadow-md transition p-4">
      {selectionActive && (
        <SelectionCheckbox selected={selected} className="absolute top-2 left-2 z-10" onClick={handleCheckboxClick} />
      )}
      <Link to={fileHref(file)} className="flex flex-col">
        <div className="flex items-start justify-between mb-3">
          <div className="w-12 h-12 rounded-lg bg-otter-50 flex items-center justify-center">
            <Icon size={24} className="text-otter-600" />
          </div>
          <div className="flex items-center gap-1">
            <StarButton
              starred={starred}
              className="p-1 rounded hover:bg-gray-100 transition"
              onClick={handleStarClick}
            />
            <FileMenuTrigger
              file={file}
              wrapperClassName="relative"
              buttonClassName="p-1 rounded hover:bg-gray-100 text-gray-400 opacity-0 group-hover:opacity-100 transition"
              onDelete={onDelete}
              onShare={onShare}
              onRename={rename.startRename}
              onDownload={onDownload}
            />
          </div>
        </div>
        {rename.isRenaming ? (
          <div className="mb-1" onClick={(e) => e.preventDefault()}>
            {renameInput}
          </div>
        ) : (
          <p className="text-sm font-medium text-gray-900 truncate mb-1">{file.name}</p>
        )}
        <p className="text-xs text-gray-500">
          {file.isFolder ? "Folder" : formatFileSize(file.size)}
          {" \u00b7 "}
          {formatRelativeTime(file.updatedAt)}
        </p>
      </Link>
    </div>
  );
}

function FileMenu({
  file,
  onClose,
  onDelete,
  onShare,
  onRename,
  onDownload,
}: {
  file: FileItem;
  onClose: () => void;
  onDelete?: (id: string) => void;
  onShare?: (id: string) => void;
  onRename?: () => void;
  onDownload?: (id: string, name: string) => void;
}) {
  return (
    <>
      <div className="fixed inset-0 z-10" onClick={onClose} />
      <div className="absolute right-0 top-full mt-1 w-40 bg-white rounded-lg shadow-lg border border-gray-200 py-1 z-20">
        <button
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onRename?.();
            onClose();
          }}
          className="flex items-center gap-2 w-full px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
        >
          <Pencil size={14} />
          Rename
        </button>
        {!file.isFolder && (
          <button
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onDownload?.(file.id, file.name);
              onClose();
            }}
            className="flex items-center gap-2 w-full px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            <Download size={14} />
            Download
          </button>
        )}
        <button
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onShare?.(file.id);
            onClose();
          }}
          className="flex items-center gap-2 w-full px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
        >
          <Share2 size={14} />
          Share
        </button>
        <button
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onDelete?.(file.id);
            onClose();
          }}
          className="flex items-center gap-2 w-full px-3 py-2 text-sm text-red-600 hover:bg-red-50"
        >
          <Trash2 size={14} />
          Delete
        </button>
      </div>
    </>
  );
}

// Re-export iconMap for external use
export { iconMap };
