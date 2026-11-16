import { AlertTriangle } from "lucide-react";
import { formatFileSize } from "@/lib/utils";
import { getStorageUsageStatus, type StorageUsageLevel } from "@/lib/storage-usage";

const barColor: Record<StorageUsageLevel, string> = {
  normal: "bg-otter-600",
  warning: "bg-amber-500",
  critical: "bg-red-600",
};

const warningColor: Record<StorageUsageLevel, string> = {
  normal: "",
  warning: "text-amber-700",
  critical: "text-red-700",
};

export function StorageUsageBar({ used, total }: Readonly<{ used: number; total: number }>) {
  const status = getStorageUsageStatus(used, total);

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-medium text-gray-700">Storage</span>
        <span className="text-sm text-gray-500">
          {formatFileSize(used)} of {formatFileSize(total)}
        </span>
      </div>
      <div
        className="w-full h-2 bg-gray-100 rounded-full overflow-hidden"
        role="progressbar"
        aria-label="Storage used"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={status.displayPercent}
      >
        <div
          className={`h-full rounded-full transition-all ${barColor[status.level]}`}
          data-level={status.level}
          style={{ width: `${status.percent}%` }}
        />
      </div>
      {status.showWarning && (
        <p
          role="status"
          className={`mt-2 flex items-center gap-1.5 text-sm font-medium ${warningColor[status.level]}`}
        >
          <AlertTriangle size={14} aria-hidden="true" />
          You&apos;re running out of space ({status.displayPercent}% used)
        </p>
      )}
    </div>
  );
}
