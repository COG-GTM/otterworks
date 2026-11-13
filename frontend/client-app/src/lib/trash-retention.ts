export const TRASH_RETENTION_DAYS = 30;
export const TRASH_URGENT_DAYS = 3;

const DAY_MS = 24 * 60 * 60 * 1000;

export interface TrashRetention {
  /** Whole days until permanent deletion; 0 when less than a day is left, negative when overdue. */
  daysLeft: number;
  deletedLabel: string;
  remainingLabel: string;
  isUrgent: boolean;
}

/**
 * Describes how long a trashed item has been in trash and how long it has
 * left before it is permanently deleted (trashedAt + TRASH_RETENTION_DAYS).
 * Returns null when trashedAt is missing or not a valid date.
 */
export function getTrashRetention(
  trashedAt: string | null | undefined,
  now: Date = new Date(),
): TrashRetention | null {
  if (!trashedAt) return null;
  const trashedMs = new Date(trashedAt).getTime();
  if (Number.isNaN(trashedMs)) return null;

  const elapsedDays = Math.max(0, Math.floor((now.getTime() - trashedMs) / DAY_MS));
  const msLeft = trashedMs + TRASH_RETENTION_DAYS * DAY_MS - now.getTime();
  const daysLeft = Math.floor(msLeft / DAY_MS);

  let remainingLabel: string;
  if (msLeft <= 0) {
    remainingLabel = "pending permanent deletion";
  } else if (daysLeft === 0) {
    remainingLabel = "less than a day left";
  } else {
    remainingLabel = `${daysLeft} ${daysLeft === 1 ? "day" : "days"} left`;
  }

  return {
    daysLeft,
    deletedLabel: elapsedDays === 0 ? "Deleted today" : `Deleted ${elapsedDays}d ago`,
    remainingLabel,
    isUrgent: daysLeft <= TRASH_URGENT_DAYS,
  };
}
