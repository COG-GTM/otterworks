import { useState } from "react";
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
import {
  NOTIFICATION_TABS,
  countUnread,
  filterNotifications,
  type NotificationTab,
} from "@/lib/notification-filters";
import type { Notification, PaginatedResponse } from "@/types";

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
  const [activeTab, setActiveTab] = useState<NotificationTab>("all");

  const { data, isLoading } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => notificationsApi.list(),
  });

  const markReadMutation = useMutation({
    mutationFn: notificationsApi.markRead,
    onMutate: async (id: string) => {
      await queryClient.cancelQueries({ queryKey: ["notifications"] });
      const previous = queryClient.getQueryData<PaginatedResponse<Notification>>([
        "notifications",
      ]);
      if (previous) {
        queryClient.setQueryData<PaginatedResponse<Notification>>(["notifications"], {
          ...previous,
          data: previous.data.map((n) => (n.id === id ? { ...n, read: true } : n)),
        });
      }
      return { previous };
    },
    onError: (_error, _id, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["notifications"], context.previous);
      }
    },
    onSettled: () => {
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
  const unreadCount = countUnread(notifications);
  const visibleNotifications = filterNotifications(notifications, activeTab);

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Notifications</h1>
          {unreadCount > 0 && (
            <p className="text-sm text-gray-500 mt-1">
              {unreadCount} unread notification{unreadCount !== 1 ? "s" : ""}
            </p>
          )}
        </div>
        {unreadCount > 0 && (
          <button
            onClick={() => markAllReadMutation.mutate()}
            disabled={markAllReadMutation.isPending}
            className="flex items-center gap-2 px-3 py-2 text-sm text-otter-600 bg-otter-50 rounded-lg hover:bg-otter-100 transition"
          >
            <CheckCheck size={16} />
            Mark all as read
          </button>
        )}
      </div>

      {/* Tabs */}
      <div
        role="tablist"
        aria-label="Filter notifications"
        className="flex gap-1 border-b border-gray-200"
      >
        {NOTIFICATION_TABS.map((tab) => {
          const selected = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={`notifications-tab-${tab.id}`}
              aria-selected={selected}
              aria-controls="notifications-panel"
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "flex items-center gap-2 px-4 py-2 -mb-px text-sm font-medium border-b-2 transition",
                selected
                  ? "border-otter-600 text-otter-700"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              )}
            >
              {tab.label}
              {tab.id === "unread" && (
                <span
                  data-testid="unread-tab-count"
                  className={cn(
                    "min-w-[1.25rem] px-1.5 py-0.5 rounded-full text-xs leading-none",
                    selected ? "bg-otter-100 text-otter-700" : "bg-gray-100 text-gray-600"
                  )}
                >
                  {unreadCount}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Notifications */}
      <div
        role="tabpanel"
        id="notifications-panel"
        aria-labelledby={`notifications-tab-${activeTab}`}
      >
        {isLoading ? (
          <PageLoader />
        ) : visibleNotifications.length === 0 ? (
          activeTab === "unread" ? (
            <EmptyState
              icon={CheckCheck}
              title="You're all caught up"
              description="You have no unread notifications."
            />
          ) : (
            <EmptyState
              icon={Bell}
              title="No notifications"
              description="New notifications will appear here."
            />
          )
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100 overflow-hidden">
            {visibleNotifications.map((notification) => (
              <NotificationRow
                key={notification.id}
                notification={notification}
                onMarkRead={() => markReadMutation.mutate(notification.id)}
              />
            ))}
          </div>
        )}
      </div>
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
  share: "text-purple-600 bg-purple-50",
  comment: "text-orange-600 bg-orange-50",
  mention: "text-blue-600 bg-blue-50",
  edit: "text-green-600 bg-green-50",
  system: "text-gray-600 bg-gray-100",
};

function NotificationRow({
  notification,
  onMarkRead,
}: Readonly<{
  notification: Notification;
  onMarkRead: () => void;
}>) {
  const Icon = notificationIcons[notification.type] || Bell;
  const color = notificationColors[notification.type] || "text-gray-600 bg-gray-100";

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
        !notification.read ? "bg-otter-50/30" : "hover:bg-gray-50"
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
        <p className="text-sm text-gray-900">
          <span className="font-medium">{notification.title}</span>
        </p>
        <p className="text-sm text-gray-500 mt-0.5">{notification.message}</p>
        <p className="text-xs text-gray-400 mt-1">
          {formatRelativeTime(notification.createdAt)}
        </p>
      </div>
      {!notification.read && (
        <div className="w-2.5 h-2.5 rounded-full bg-otter-600 flex-shrink-0 mt-1.5" />
      )}
    </div>
  );

  if (href) {
    return <Link to={href}>{content}</Link>;
  }

  return content;
}
