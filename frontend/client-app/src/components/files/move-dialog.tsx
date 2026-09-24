import { useQuery } from "@tanstack/react-query";
import { Folder, HardDrive, X } from "lucide-react";
import { filesApi } from "@/lib/api";

interface MoveDialogProps {
  count: number;
  currentFolderId: string | null;
  onMove: (folderId: string | null) => void;
  onClose: () => void;
}

export function MoveDialog({ count, currentFolderId, onMove, onClose }: Readonly<MoveDialogProps>) {
  const { data: folders, isLoading } = useQuery({
    queryKey: ["folders", "list", null],
    queryFn: () => filesApi.listFolders(null),
  });

  const targets = (folders ?? []).filter((f) => f.id !== currentFolderId);

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40">
      <div className="w-full sm:max-w-md bg-white rounded-t-xl sm:rounded-xl max-h-[70vh] flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <h2 className="text-sm font-semibold text-gray-900">
            Move {count} item{count > 1 ? "s" : ""} to
          </h2>
          <button
            onClick={onClose}
            aria-label="Close move dialog"
            className="min-h-[44px] min-w-[44px] flex items-center justify-center text-gray-500"
          >
            <X size={18} />
          </button>
        </div>
        <div className="overflow-y-auto">
          {currentFolderId !== null && (
            <MoveTarget label="Files (root)" icon={HardDrive} onClick={() => onMove(null)} />
          )}
          {isLoading && <p className="px-4 py-3 text-sm text-gray-500">Loading folders…</p>}
          {!isLoading && targets.length === 0 && currentFolderId === null && (
            <p className="px-4 py-3 text-sm text-gray-500">No folders to move into.</p>
          )}
          {targets.map((folder) => (
            <MoveTarget
              key={folder.id}
              label={folder.name}
              icon={Folder}
              onClick={() => onMove(folder.id)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function MoveTarget({
  label,
  icon: Icon,
  onClick,
}: Readonly<{ label: string; icon: typeof Folder; onClick: () => void }>) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-3 w-full px-4 min-h-[44px] py-2 text-sm text-gray-800 hover:bg-gray-50 active:bg-gray-100"
    >
      <Icon size={18} className="text-amber-600 flex-shrink-0" />
      <span className="truncate">{label}</span>
    </button>
  );
}
