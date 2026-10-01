import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  Share2,
  MessageSquare,
  AtSign,
  Edit3,
  Info,
  CheckCheck,
} from "lucide-react";
import { Link } from "react-router-dom";
import { AppShell } from "@/components/layout/app-shell";
import { PageLoader } from "@/components/ui/loading-spinner";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { notificationsApi } from "@/lib/api";
import { formatRelativeTime, cn, getInitials, generateColor } from "@/lib/utils";
import type { Notification } from "@/types";

export default function NotificationsPage() {
  return (
    <AppShell>
      <ErrorBoundary>
        <NotificationsContent />
      </ErrorBoundary>
    </AppShell>
  );
}

function NotificationsContent() {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => notificationsApi.list(),
  });

  const markReadMutation = useMutation({
    mutationFn: notificationsApi.markRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  const markAllReadMutation = useMutation({
    mutationFn: notificationsApi.markAllRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  const notifications = data?.data || [];
  const unreadCount = notifications.filter((n) => !n.read).length;

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Notifications</h1>
          {unreadCount > 0 && (
            <p className="text-sm text-slate-400 mt-1">
              {unreadCount} unread notification{unreadCount !== 1 ? "s" : ""}
            </p>
          )}
        </div>
        {unreadCount > 0 && (
          <button
            onClick={() => markAllReadMutation.mutate()}
            disabled={markAllReadMutation.isPending}
            className="flex items-center gap-2 px-3 py-2 text-sm text-otter-200 bg-otter-500/15 rounded-lg hover:bg-otter-500/25 transition"
          >
            <CheckCheck size={16} />
            Mark all as read
          </button>
        )}
      </div>

      {/* Notifications */}
      {isLoading ? (
        <PageLoader />
      ) : notifications.length === 0 ? (
        <EmptyState
          icon={Bell}
          title="No notifications"
          description="You&apos;re all caught up! New notifications will appear here."
        />
      ) : (
        <div className="bg-surface rounded-xl border border-line divide-y divide-line overflow-hidden">
          {notifications.map((notification) => (
            <NotificationRow
              key={notification.id}
              notification={notification}
              onMarkRead={() => markReadMutation.mutate(notification.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

const notificationIcons: Record<string, typeof Bell> = {
  share: Share2,
  comment: MessageSquare,
  mention: AtSign,
  edit: Edit3,
  system: Info,
};

const notificationColors: Record<string, string> = {
  share: "text-purple-300 bg-purple-500/10",
  comment: "text-orange-300 bg-orange-500/10",
  mention: "text-blue-300 bg-blue-500/10",
  edit: "text-green-300 bg-green-500/10",
  system: "text-slate-300 bg-surface-raised",
};

function NotificationRow({
  notification,
  onMarkRead,
}: Readonly<{
  notification: Notification;
  onMarkRead: () => void;
}>) {
  const Icon = notificationIcons[notification.type] || Bell;
  const color = notificationColors[notification.type] || "text-slate-300 bg-surface-raised";

  const href =
    notification.resourceId && notification.resourceType === "document"
      ? `/documents/${notification.resourceId}`
      : notification.resourceId && notification.resourceType === "file"
      ? `/files/${notification.resourceId}`
      : undefined;

  const handleActivate = () => {
    if (!notification.read) onMarkRead();
  };

  const content = (
    <div
      role="button"
      tabIndex={0}
      className={cn(
        "flex items-start gap-4 px-5 py-4 transition cursor-pointer",
        !notification.read ? "bg-otter-500/10 hover:bg-otter-500/15" : "hover:bg-surface-raised"
      )}
      onClick={handleActivate}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          handleActivate();
        }
      }}
    >
      {notification.actorName ? (
        <div
          className="w-10 h-10 rounded-full flex items-center justify-center text-xs font-bold text-white flex-shrink-0"
          style={{
            backgroundColor: generateColor(notification.actorId || notification.actorName),
          }}
        >
          {getInitials(notification.actorName)}
        </div>
      ) : (
        <div
          className={cn(
            "w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0",
            color
          )}
        >
          <Icon size={18} />
        </div>
      )}
      <div className="flex-1 min-w-0">
        <p className="text-sm text-slate-100">
          <span className="font-medium">{notification.title}</span>
        </p>
        <p className="text-sm text-slate-400 mt-0.5">{notification.message}</p>
        <p className="text-xs text-slate-500 mt-1">
          {formatRelativeTime(notification.createdAt)}
        </p>
      </div>
      {!notification.read && (
        <div className="w-2.5 h-2.5 rounded-full bg-otter-400 flex-shrink-0 mt-1.5" />
      )}
    </div>
  );

  if (href) {
    return <Link to={href}>{content}</Link>;
  }

  return content;
}
