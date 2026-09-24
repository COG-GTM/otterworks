import { Link } from "react-router-dom";
import { Folder, MoreVertical, Trash2, Share2, Pencil } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import type { FileItem } from "@/types";
import { formatRelativeTime, cn } from "@/lib/utils";
import { actionRevealClass, isInteractiveTarget, tapTargetClass, useCoarsePointer, useLongPress } from "@/lib/touch";

interface FolderCardProps {
  folder: FileItem;
  onDelete?: (id: string) => void;
  onShare?: (id: string) => void;
  onRename?: (id: string, name: string) => void;
  view?: "grid" | "list";
  selected?: boolean;
  onSelect?: (id: string) => void;
  selectionActive?: boolean;
  onLongPress?: (id: string) => void;
}

export function FolderCard({
  folder,
  onDelete,
  onShare,
  onRename,
  view = "grid",
  selected = false,
  onSelect,
  selectionActive = false,
  onLongPress,
}: FolderCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const coarsePointer = useCoarsePointer();
  const revealClass = actionRevealClass(coarsePointer);
  const tapClass = tapTargetClass(coarsePointer);
  const { handlers: longPressHandlers, consumeLongPress } = useLongPress(
    onLongPress ? () => onLongPress(folder.id) : undefined,
    { enabled: coarsePointer }
  );

  const handleCardClickCapture = (e: React.MouseEvent) => {
    if (!coarsePointer) return;
    const longPressed = consumeLongPress();
    if (isInteractiveTarget(e.target)) return;
    if (longPressed || (selectionActive && onSelect)) {
      e.preventDefault();
      e.stopPropagation();
      if (!longPressed) onSelect?.(folder.id);
    }
  };
  const [isRenaming, setIsRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState(folder.name);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const renameDoneRef = useRef(false);

  useEffect(() => {
    if (isRenaming && renameInputRef.current) {
      renameInputRef.current.focus();
      renameInputRef.current.select();
    }
  }, [isRenaming]);

  const submitRename = () => {
    if (renameDoneRef.current) return;
    renameDoneRef.current = true;
    const trimmed = renameValue.trim();
    if (trimmed && trimmed !== folder.name) {
      onRename?.(folder.id, trimmed);
    }
    setIsRenaming(false);
  };

  const handleCheckboxClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onSelect?.(folder.id);
  };

  if (view === "list") {
    return (
      <div
        className={cn(
          "flex items-center gap-4 px-4 py-2.5 hover:bg-gray-50 rounded-lg transition group border-b border-gray-100 last:border-0",
          selected && "bg-otter-50"
        )}
        onClickCapture={handleCardClickCapture}
        {...longPressHandlers}
      >
        {selectionActive && (
          <div className="flex-shrink-0" onClick={handleCheckboxClick}>
            <input
              type="checkbox"
              checked={selected}
              readOnly
              className="h-4 w-4 rounded border-gray-300 text-otter-600 focus:ring-otter-500 cursor-pointer"
            />
          </div>
        )}
        <Link
          to={`/files?folder=${folder.id}`}
          className="flex items-center gap-4 flex-1 min-w-0"
        >
          <div className="w-10 h-10 rounded-lg bg-amber-50 flex items-center justify-center flex-shrink-0">
            <Folder size={20} className="text-amber-600" />
          </div>
          <div className="flex-1 min-w-0">
            {isRenaming ? (
              <div className="flex items-center gap-1" onClick={(e) => e.preventDefault()}>
                <input
                  ref={renameInputRef}
                  type="text"
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") submitRename();
                    if (e.key === "Escape") { renameDoneRef.current = true; setIsRenaming(false); setRenameValue(folder.name); }
                  }}
                  onBlur={submitRename}
                  className="text-sm font-medium text-gray-900 px-1 py-0.5 border border-otter-400 rounded focus:outline-none focus:ring-1 focus:ring-otter-500 w-full"
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}
                />
              </div>
            ) : (
              <p className="text-sm font-medium text-gray-900 truncate">{folder.name}</p>
            )}
          </div>
          <span className="text-xs text-gray-500 w-32 hidden sm:block truncate">
            {formatRelativeTime(folder.updatedAt)}
          </span>
          <span className="text-xs text-gray-400 w-20 hidden sm:block text-right">&mdash;</span>
        </Link>
        <div className={cn("relative", coarsePointer ? "w-11" : "w-8")}>
          <button
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setMenuOpen(!menuOpen);
            }}
            aria-label="Folder actions"
            className={cn(
              "p-1 rounded hover:bg-gray-200 text-gray-400 transition",
              tapClass,
              revealClass
            )}
          >
            <MoreVertical size={16} />
          </button>
          {menuOpen && (
            <FolderMenu
              folder={folder}
              onClose={() => setMenuOpen(false)}
              onDelete={onDelete}
              onShare={onShare}
              onRename={() => { renameDoneRef.current = false; setIsRenaming(true); setRenameValue(folder.name); }}
            />
          )}
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group relative flex flex-col rounded-xl border bg-white hover:shadow-md transition p-4",
        selected ? "border-otter-400 bg-otter-50" : "border-gray-200"
      )}
      onClickCapture={handleCardClickCapture}
      {...longPressHandlers}
    >
      {selectionActive && (
        <div className="absolute top-2 left-2 z-10" onClick={handleCheckboxClick}>
          <input
            type="checkbox"
            checked={selected}
            readOnly
            className="h-4 w-4 rounded border-gray-300 text-otter-600 focus:ring-otter-500 cursor-pointer"
          />
        </div>
      )}
      <Link
        to={`/files?folder=${folder.id}`}
        className="flex flex-col"
      >
        <div className="flex items-start justify-between mb-3">
          <div className="w-12 h-12 rounded-lg bg-amber-50 flex items-center justify-center">
            <Folder size={24} className="text-amber-600" />
          </div>
          <div className="relative">
            <button
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setMenuOpen(!menuOpen);
              }}
              aria-label="Folder actions"
              className={cn(
                "p-1 rounded hover:bg-gray-100 text-gray-400 transition",
                tapClass,
                revealClass
              )}
            >
              <MoreVertical size={16} />
            </button>
            {menuOpen && (
              <FolderMenu
                folder={folder}
                onClose={() => setMenuOpen(false)}
                onDelete={onDelete}
                onShare={onShare}
                onRename={() => { renameDoneRef.current = false; setIsRenaming(true); setRenameValue(folder.name); }}
              />
            )}
          </div>
        </div>
        {isRenaming ? (
          <div className="mb-1" onClick={(e) => e.preventDefault()}>
            <input
              ref={renameInputRef}
              type="text"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submitRename();
                if (e.key === "Escape") { renameDoneRef.current = true; setIsRenaming(false); setRenameValue(folder.name); }
              }}
              onBlur={submitRename}
              className="text-sm font-medium text-gray-900 px-1 py-0.5 border border-otter-400 rounded focus:outline-none focus:ring-1 focus:ring-otter-500 w-full"
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}
            />
          </div>
        ) : (
          <p className="text-sm font-medium text-gray-900 truncate mb-1">{folder.name}</p>
        )}
        <p className="text-xs text-gray-500">
          Folder &middot; {formatRelativeTime(folder.updatedAt)}
        </p>
      </Link>
    </div>
  );
}

function FolderMenu({
  folder,
  onClose,
  onDelete,
  onShare,
  onRename,
}: {
  folder: FileItem;
  onClose: () => void;
  onDelete?: (id: string) => void;
  onShare?: (id: string) => void;
  onRename?: () => void;
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
        <button
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onShare?.(folder.id);
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
            onDelete?.(folder.id);
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
