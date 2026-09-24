import { Download, Share2, Star, FolderInput, Trash2, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface SelectionActionBarProps {
  count: number;
  onDownload: () => void;
  onShare: () => void;
  onStar: () => void;
  onMove: () => void;
  onTrash: () => void;
  onCancel: () => void;
  shareDisabled?: boolean;
  downloadDisabled?: boolean;
  moveDisabled?: boolean;
}

// Sticky bottom bar for touch multi-select: the hover-only card menus are not
// reachable with a finger, so bulk actions live here instead.
export function SelectionActionBar({
  count,
  onDownload,
  onShare,
  onStar,
  onMove,
  onTrash,
  onCancel,
  shareDisabled = false,
  downloadDisabled = false,
  moveDisabled = false,
}: Readonly<SelectionActionBarProps>) {
  return (
    <div
      data-testid="selection-action-bar"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-gray-200 bg-white shadow-[0_-2px_8px_rgba(0,0,0,0.08)]"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-gray-100">
        <span className="text-sm font-medium text-otter-800">{count} selected</span>
        <button
          onClick={onCancel}
          aria-label="Cancel selection"
          className="min-h-[44px] min-w-[44px] flex items-center justify-center text-gray-500"
        >
          <X size={18} />
        </button>
      </div>
      <div className="flex items-stretch justify-between px-1 py-1">
        <BarAction label="Download" icon={Download} onClick={onDownload} disabled={downloadDisabled} />
        <BarAction label="Share" icon={Share2} onClick={onShare} disabled={shareDisabled} />
        <BarAction label="Star" icon={Star} onClick={onStar} />
        <BarAction label="Move" icon={FolderInput} onClick={onMove} disabled={moveDisabled} />
        <BarAction label="Trash" icon={Trash2} onClick={onTrash} danger />
      </div>
    </div>
  );
}

function BarAction({
  label,
  icon: Icon,
  onClick,
  disabled = false,
  danger = false,
}: Readonly<{
  label: string;
  icon: typeof Download;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
}>) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex-1 min-w-[44px] min-h-[44px] flex flex-col items-center justify-center gap-0.5 px-1 py-1.5 rounded transition",
        danger ? "text-red-600" : "text-gray-700",
        disabled ? "opacity-40" : "active:bg-gray-100"
      )}
    >
      <Icon size={18} />
      <span className="text-[11px] leading-none">{label}</span>
    </button>
  );
}
