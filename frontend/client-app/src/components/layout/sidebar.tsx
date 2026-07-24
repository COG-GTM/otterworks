import { Link, useLocation } from "react-router-dom";
import {
  Home,
  Clock,
  FolderOpen,
  FileText,
  Search,
  Bell,
  Settings,
  Share2,
  Trash2,
  Star,
  TrendingUp,
  Menu,
  X,
  Plus,
  LogOut,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useUIStore } from "@/stores/ui-store";
import { useAuthStore } from "@/stores/auth-store";
import { getInitials } from "@/lib/utils";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: Home },
  { href: "/recent", label: "Recent", icon: Clock },
  { href: "/files", label: "Files", icon: FolderOpen },
  { href: "/documents", label: "Documents", icon: FileText },
  { href: "/search", label: "Search", icon: Search },
  { href: "/shared", label: "Shared with me", icon: Share2 },
  { href: "/starred", label: "Starred", icon: Star },
  { href: "/margins", label: "Margins", icon: TrendingUp },
  { href: "/notifications", label: "Notifications", icon: Bell },
  { href: "/trash", label: "Trash", icon: Trash2 },
];

const bottomItems = [
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const { pathname } = useLocation();
  const { sidebarOpen, toggleSidebar } = useUIStore();
  const { user, logout } = useAuthStore();

  return (
    <>
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={toggleSidebar}
        />
      )}

      <aside
        className={cn(
          "fixed top-0 left-0 z-50 h-full bg-white border-r border-gray-200 transition-transform duration-200 flex flex-col",
          "w-64",
          sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0 lg:w-16"
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between h-16 px-4 border-b border-gray-200">
          {sidebarOpen && (
            <Link to="/dashboard" className="flex items-center gap-2">
              <div className="w-8 h-8 bg-otter-600 rounded-lg flex items-center justify-center">
                <span className="text-white font-bold text-sm">OW</span>
              </div>
              <span className="font-semibold text-gray-900">OtterWorks</span>
            </Link>
          )}
          <button
            onClick={toggleSidebar}
            className="p-2 rounded-lg hover:bg-gray-100 text-gray-500"
            aria-label="Toggle sidebar"
          >
            {sidebarOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>

        {/* New button */}
        {sidebarOpen && (
          <div className="p-4">
            <Link
              to="/files"
              className="flex items-center justify-center gap-2 w-full px-4 py-2.5 bg-otter-600 text-white rounded-lg hover:bg-otter-700 transition font-medium text-sm"
            >
              <Plus size={18} />
              New
            </Link>
          </div>
        )}

        {/* Navigation */}
        <nav className="flex-1 px-3 py-2 overflow-y-auto">
          <ul className="space-y-1">
            {navItems.map((item) => {
              const isActive =
                pathname === item.href || pathname.startsWith(item.href + "/");
              return (
                <li key={item.href}>
                  <Link
                    to={item.href}
                    className={cn(
                      "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition",
                      isActive
                        ? "bg-otter-50 text-otter-700"
                        : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                    )}
                  >
                    <item.icon size={20} />
                    {sidebarOpen && <span>{item.label}</span>}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        {/* Bottom section */}
        <div className="border-t border-gray-200 px-3 py-2">
          {bottomItems.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.href}
                to={item.href}
                className={cn(
                  "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition",
                  isActive
                    ? "bg-otter-50 text-otter-700"
                    : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                )}
              >
                <item.icon size={20} />
                {sidebarOpen && <span>{item.label}</span>}
              </Link>
            );
          })}

          {/* User profile */}
          {user && sidebarOpen && (
            <div className="flex items-center gap-3 px-3 py-3 mt-2">
              <div className="w-8 h-8 rounded-full bg-otter-100 text-otter-700 flex items-center justify-center text-xs font-semibold">
                {getInitials(user.displayName)}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900 truncate">
                  {user.displayName}
                </p>
                <p className="text-xs text-gray-500 truncate">{user.email}</p>
              </div>
              <button
                onClick={logout}
                className="p-1.5 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600"
                aria-label="Sign out"
              >
                <LogOut size={16} />
              </button>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
