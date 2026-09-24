import { useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  FolderOpen,
  FileText,
  Clock,
  HardDrive,
  TrendingUp,
  Plus,
  ArrowRight,
} from "lucide-react";
import { Link } from "react-router-dom";
import { AppShell } from "@/components/layout/app-shell";
import { FileCard } from "@/components/files/file-card";
import { DocumentCard } from "@/components/documents/document-card";
import { DashboardSkeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { filesApi, documentsApi, activityApi, storageApi } from "@/lib/api";
import { formatFileSize, formatRelativeTime } from "@/lib/utils";
import type { ActivityItem } from "@/types";

export default function DashboardPage() {
  return (
    <AppShell>
      <ErrorBoundary>
        <DashboardContent />
      </ErrorBoundary>
    </AppShell>
  );
}

function DashboardContent() {
  const { data: recentFiles, isLoading: filesLoading } = useQuery({
    queryKey: ["files", "recent"],
    queryFn: () => filesApi.getRecent(6),
  });

  const { data: recentDocs, isLoading: docsLoading } = useQuery({
    queryKey: ["documents", "recent"],
    queryFn: () => documentsApi.getRecent(6),
  });

  const { data: activity, isLoading: activityLoading } = useQuery({
    queryKey: ["activity", "recent"],
    queryFn: () => activityApi.getRecent(10),
  });

  const { data: storage } = useQuery({
    queryKey: ["storage", "usage"],
    queryFn: () => storageApi.getUsage(),
  });

  const isLoading = filesLoading || docsLoading || activityLoading;

  if (isLoading) return <DashboardSkeleton />;

  return (
    <div className="max-w-7xl mx-auto space-y-8">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-1">
            Welcome back! Here&apos;s your latest activity.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to="/files"
            className="flex items-center gap-2 px-4 py-2 bg-otter-600 text-white rounded-lg hover:bg-otter-700 transition text-sm font-medium"
          >
            <Plus size={16} />
            Upload file
          </Link>
          <Link
            to="/documents"
            className="flex items-center gap-2 px-4 py-2 bg-white text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50 transition text-sm font-medium"
          >
            <FileText size={16} />
            New document
          </Link>
        </div>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={FolderOpen}
          label="Total files"
          value={storage?.fileCount?.toString() || "0"}
          color="blue"
        />
        <StatCard
          icon={FileText}
          label="Documents"
          value={storage?.documentCount?.toString() || "0"}
          color="purple"
        />
        <StatCard
          icon={HardDrive}
          label="Storage used"
          value={storage ? formatFileSize(storage.used) : "0 B"}
          subtitle={storage ? `of ${formatFileSize(storage.limit)}` : undefined}
          color="green"
        />
        <StatCard
          icon={TrendingUp}
          label="Recent activity"
          value={activity?.length?.toString() || "0"}
          subtitle="actions today"
          color="orange"
        />
      </div>

      {/* Storage progress */}
      {storage && (
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium text-gray-700">Storage</span>
            <span className="text-sm text-gray-500">
              {formatFileSize(storage.used)} of {formatFileSize(storage.limit)} (
              {Math.round(storage.percentUsed)}%)
            </span>
          </div>
          <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-otter-600 rounded-full transition-all"
              style={{
                width: `${Math.min(storage.percentUsed, 100)}%`,
              }}
            />
          </div>
        </div>
      )}

      {/* Recent files */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">Recent files</h2>
          <Link
            to="/files"
            className="flex items-center gap-1 text-sm text-otter-600 hover:text-otter-700 font-medium"
          >
            View all <ArrowRight size={14} />
          </Link>
        </div>
        {recentFiles && recentFiles.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {recentFiles.map((file) => (
              <FileCard
                key={file.id}
                file={file}
                view="grid"
                onDownload={async (id, name) => {
                  try {
                    const downloadUrl = await filesApi.getDownloadUrl(id);
                    const a = document.createElement("a");
                    a.href = downloadUrl;
                    a.download = name;
                    a.rel = "noopener";
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    toast.success("File downloaded successfully");
                  } catch {
                    toast.error("Download failed. Please try again.");
                  }
                }}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            icon={FolderOpen}
            title="No recent files"
            description="Upload files to get started"
          />
        )}
      </section>

      {/* Recent documents */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">Recent documents</h2>
          <Link
            to="/documents"
            className="flex items-center gap-1 text-sm text-otter-600 hover:text-otter-700 font-medium"
          >
            View all <ArrowRight size={14} />
          </Link>
        </div>
        {recentDocs && recentDocs.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {recentDocs.map((doc) => (
              <DocumentCard key={doc.id} document={doc} view="grid" />
            ))}
          </div>
        ) : (
          <EmptyState
            icon={FileText}
            title="No recent documents"
            description="Create a document to start collaborating"
          />
        )}
      </section>

      {/* Activity feed */}
      <section>
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Activity</h2>
        {activity && activity.length > 0 ? (
          <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
            {activity.map((item) => (
              <ActivityRow key={item.id} item={item} />
            ))}
          </div>
        ) : (
          <EmptyState
            icon={Clock}
            title="No recent activity"
            description="Your activity will appear here"
          />
        )}
      </section>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  subtitle,
  color,
}: Readonly<{
  icon: typeof FolderOpen;
  label: string;
  value: string;
  subtitle?: string;
  color: "blue" | "purple" | "green" | "orange";
}>) {
  const colorClasses = {
    blue: "bg-blue-50 text-blue-600",
    purple: "bg-purple-50 text-purple-600",
    green: "bg-green-50 text-green-600",
    orange: "bg-orange-50 text-orange-600",
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-center gap-3">
        <div
          className={`w-10 h-10 rounded-lg flex items-center justify-center ${colorClasses[color]}`}
        >
          <Icon size={20} />
        </div>
        <div>
          <p className="text-2xl font-bold text-gray-900">{value}</p>
          <p className="text-xs text-gray-500">
            {label}
            {subtitle && ` \u00B7 ${subtitle}`}
          </p>
        </div>
      </div>
    </div>
  );
}

function ActivityRow({ item }: Readonly<{ item: ActivityItem }>) {
  const iconMap: Record<string, string> = {
    upload: "text-blue-600",
    edit: "text-green-600",
    share: "text-purple-600",
    comment: "text-orange-600",
    delete: "text-red-600",
    restore: "text-teal-600",
  };

  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <div
        className={`w-2 h-2 rounded-full flex-shrink-0 ${
          iconMap[item.type]?.replace("text-", "bg-") || "bg-gray-400"
        }`}
      />
      <div className="flex-1 min-w-0">
        <p className="text-sm text-gray-700">
          <span className="font-medium">{item.actorName}</span>{" "}
          {item.description}
        </p>
      </div>
      <span className="text-xs text-gray-400 flex-shrink-0">
        {formatRelativeTime(item.createdAt)}
      </span>
    </div>
  );
}
