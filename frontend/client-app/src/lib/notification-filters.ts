import type { Notification } from "@/types";

export type NotificationTab = "all" | "unread";

export const NOTIFICATION_TABS: ReadonlyArray<{ id: NotificationTab; label: string }> = [
  { id: "all", label: "All" },
  { id: "unread", label: "Unread" },
];

export function filterNotifications(
  notifications: readonly Notification[],
  tab: NotificationTab
): Notification[] {
  if (tab === "unread") {
    return notifications.filter((n) => !n.read);
  }
  return [...notifications];
}

export function countUnread(notifications: readonly Notification[]): number {
  return notifications.reduce((count, n) => (n.read ? count : count + 1), 0);
}
