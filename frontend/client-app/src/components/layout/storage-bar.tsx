import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { HardDrive } from "lucide-react";
import { storageApi } from "@/lib/api";
import { cn, formatFileSize } from "@/lib/utils";

const WARN_PERCENT = 80;
const CRITICAL_PERCENT = 95;

function barColor(percentUsed: number): string {
  if (percentUsed >= CRITICAL_PERCENT) return "bg-red-500";
  if (percentUsed >= WARN_PERCENT) return "bg-amber-400";
  return "bg-accent-500";
}

interface StorageBarProps {
  collapsed?: boolean;
}

export function StorageBar({ collapsed = false }: StorageBarProps) {
  const { data: storage } = useQuery({
    queryKey: ["storage", "usage"],
    queryFn: () => storageApi.getUsage(),
  });

  if (!storage) return null;

  const percent = Math.min(storage.percentUsed, 100);
  const color = barColor(storage.percentUsed);

  if (collapsed) {
    return (
      <Link
        to="/settings"
        title={`${formatFileSize(storage.used)} of ${formatFileSize(storage.limit)} used`}
        className="flex flex-col items-center gap-1 py-2 text-otter-200 hover:text-white"
        data-testid="sidebar-storage-bar"
      >
        <HardDrive size={18} />
        <div className="w-8 h-1 bg-otter-800 rounded-full overflow-hidden">
          <div className={cn("h-full rounded-full", color)} style={{ width: `${percent}%` }} />
        </div>
      </Link>
    );
  }

  return (
    <div className="px-1 py-2" data-testid="sidebar-storage-bar">
      <div className="flex items-center gap-2 mb-1.5 text-otter-100">
        <HardDrive size={14} />
        <span className="text-xs font-medium">Storage</span>
        <span className="ml-auto text-[11px] text-otter-200">
          {Math.round(storage.percentUsed)}%
        </span>
      </div>
      <div className="w-full h-1.5 bg-otter-800 rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all", color)}
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="mt-1.5 text-[11px] text-otter-200">
        {formatFileSize(storage.used)} of {formatFileSize(storage.limit)} used
      </p>
      {storage.percentUsed >= WARN_PERCENT && (
        <Link to="/trash" className="text-[11px] font-medium text-white underline">
          Free up space
        </Link>
      )}
    </div>
  );
}
