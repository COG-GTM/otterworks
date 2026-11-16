import type { Notification } from "@/types";

export type NotificationGroupKey = "today" | "yesterday" | "earlier";

export interface NotificationGroup {
  key: NotificationGroupKey;
  label: string;
  notifications: Notification[];
}

const GROUP_LABELS: Record<NotificationGroupKey, string> = {
  today: "Today",
  yesterday: "Yesterday",
  earlier: "Earlier",
};

const GROUP_ORDER: NotificationGroupKey[] = ["today", "yesterday", "earlier"];

function startOfLocalDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

/**
 * Groups notifications into Today / Yesterday / Earlier using the viewer's
 * local calendar days, newest first within each group. Empty groups are omitted.
 */
export function groupNotificationsByDay(
  notifications: readonly Notification[],
  now: Date = new Date()
): NotificationGroup[] {
  const startOfToday = startOfLocalDay(now).getTime();
  const yesterday = startOfLocalDay(now);
  yesterday.setDate(yesterday.getDate() - 1);
  const startOfYesterday = yesterday.getTime();

  const buckets: Record<NotificationGroupKey, Notification[]> = {
    today: [],
    yesterday: [],
    earlier: [],
  };

  const sorted = [...notifications].sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  );

  for (const notification of sorted) {
    const createdAt = new Date(notification.createdAt).getTime();
    if (createdAt >= startOfToday) buckets.today.push(notification);
    else if (createdAt >= startOfYesterday) buckets.yesterday.push(notification);
    else buckets.earlier.push(notification);
  }

  return GROUP_ORDER.filter((key) => buckets[key].length > 0).map((key) => ({
    key,
    label: GROUP_LABELS[key],
    notifications: buckets[key],
  }));
}
