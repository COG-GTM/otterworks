import { Link } from "react-router-dom";
import { Bell } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { notificationsApi } from "@/lib/api";

export function NotificationBell() {
  const { data: unreadCount = 0 } = useQuery({
    queryKey: ["notifications", "unread-count"],
    queryFn: () => notificationsApi.getUnreadCount(),
    refetchInterval: 30000,
  });

  return (
    <Link
      to="/notifications"
      className="relative p-2 rounded-lg hover:bg-surface-hover text-slate-400 hover:text-slate-200 transition"
      aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ""}`}
    >
      <Bell size={20} />
      {unreadCount > 0 && (
        <span className="absolute -top-0.5 -right-0.5 flex items-center justify-center w-5 h-5 bg-red-500 text-white text-[10px] font-bold rounded-full">
          {unreadCount > 99 ? "99+" : unreadCount}
        </span>
      )}
    </Link>
  );
}
