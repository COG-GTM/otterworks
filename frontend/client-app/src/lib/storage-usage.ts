export type StorageUsageLevel = "normal" | "warning" | "critical";

export const STORAGE_WARNING_PERCENT = 80;
export const STORAGE_CRITICAL_PERCENT = 95;

export interface StorageUsageStatus {
  /** Exact share of the quota in use, clamped to 0-100. */
  percent: number;
  /** Whole percent for display, rounded down so it never overstates a threshold. */
  displayPercent: number;
  level: StorageUsageLevel;
  showWarning: boolean;
}

export function getStorageUsageStatus(used: number, total: number): StorageUsageStatus {
  const raw = total > 0 && used > 0 ? (used / total) * 100 : 0;
  const percent = Math.min(raw, 100);

  let level: StorageUsageLevel = "normal";
  if (percent >= STORAGE_CRITICAL_PERCENT) level = "critical";
  else if (percent >= STORAGE_WARNING_PERCENT) level = "warning";

  return {
    percent,
    displayPercent: Math.floor(percent),
    level,
    showWarning: level !== "normal",
  };
}
