import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Folder, HardDrive, X } from "lucide-react";
import { filesApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { FileItem } from "@/types";

interface MoveDialogProps {
  items: FileItem[];
  currentFolderId: string | null;
  onClose: () => void;
  onMove: (targetFolderId: string | null) => void;
}

interface Crumb {
  id: string | null;
  name: string;
}

const ROOT: Crumb = { id: null, name: "My Drive" };

export function MoveDialog({ items, currentFolderId, onClose, onMove }: MoveDialogProps) {
  const [trail, setTrail] = useState<Crumb[]>([ROOT]);
  const target = trail[trail.length - 1];
  const movingFolderIds = new Set(items.filter((i) => i.isFolder).map((i) => i.id));

  const { data: folders, isLoading } = useQuery({
    queryKey: ["folders", "list", target.id],
    queryFn: () => filesApi.listFolders(target.id),
  });

  const alreadyThere = target.id === currentFolderId;
  const label =
    items.length === 1 ? `"${items[0].name}"` : `${items.length} items`;

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-0 sm:p-4">
      <div className="bg-white w-full sm:max-w-md rounded-t-2xl sm:rounded-2xl shadow-xl flex flex-col max-h-[85vh]">
        <div className="flex items-start justify-between gap-3 px-4 py-3 border-b border-gray-200">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-gray-900">Move to&hellip;</h2>
            <p className="text-xs text-gray-500 truncate">Moving {label}</p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="p-1 rounded hover:bg-gray-100 text-gray-500"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex items-center gap-1 px-4 py-2 text-sm text-gray-600 overflow-x-auto border-b border-gray-100">
          {trail.map((crumb, idx) => (
            <span key={crumb.id ?? "root"} className="flex items-center gap-1 flex-shrink-0">
              {idx > 0 && <ChevronRight size={14} className="text-gray-400" />}
              <button
                onClick={() => setTrail(trail.slice(0, idx + 1))}
                className={cn(
                  "px-1 py-0.5 rounded hover:bg-gray-100 truncate max-w-[10rem]",
                  idx === trail.length - 1 && "font-medium text-gray-900",
                )}
              >
                {idx === 0 ? (
                  <span className="flex items-center gap-1">
                    <HardDrive size={14} />
                    {crumb.name}
                  </span>
                ) : (
                  crumb.name
                )}
              </button>
            </span>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto px-2 py-2 min-h-[10rem]">
          {isLoading ? (
            <p className="px-2 py-4 text-sm text-gray-500">Loading folders&hellip;</p>
          ) : (folders ?? []).length === 0 ? (
            <p className="px-2 py-4 text-sm text-gray-500">No subfolders here</p>
          ) : (
            (folders ?? []).map((folder) => {
              const blocked = movingFolderIds.has(folder.id);
              return (
                <button
                  key={folder.id}
                  disabled={blocked}
                  title={blocked ? "A folder cannot be moved into itself" : undefined}
                  onClick={() => setTrail([...trail, { id: folder.id, name: folder.name }])}
                  className={cn(
                    "flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-left text-sm",
                    blocked
                      ? "text-gray-400 cursor-not-allowed"
                      : "text-gray-800 hover:bg-gray-50",
                  )}
                >
                  <Folder
                    size={18}
                    className={blocked ? "text-gray-300" : "text-amber-500"}
                  />
                  <span className="flex-1 truncate">{folder.name}</span>
                  {!blocked && <ChevronRight size={16} className="text-gray-400" />}
                </button>
              );
            })
          )}
        </div>

        <div className="flex items-center justify-between gap-2 px-4 py-3 border-t border-gray-200">
          <p className="text-xs text-gray-500 truncate">
            {alreadyThere ? "Items are already here" : `Destination: ${target.name}`}
          </p>
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              onClick={onClose}
              className="px-3 py-1.5 text-sm text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              disabled={alreadyThere}
              onClick={() => onMove(target.id)}
              className={cn(
                "px-3 py-1.5 text-sm text-white rounded-lg",
                alreadyThere
                  ? "bg-otter-300 cursor-not-allowed"
                  : "bg-otter-600 hover:bg-otter-700",
              )}
            >
              Move here
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
