import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { Clock, FileText, Folder, Loader2, type LucideIcon } from "lucide-react";
import { useParams } from "react-router-dom";
import { Logo } from "@/components/ui/logo";
import { filesApi } from "@/lib/api";
import { formatFileSize, formatRelativeTime } from "@/lib/utils";

export default function SharedFolderPage() {
  const { token = "" } = useParams<{ token: string }>();
  const sharedFolderQuery = useQuery({
    queryKey: ["shared-folder", token],
    queryFn: () => filesApi.getSharedFolder(token),
    enabled: Boolean(token),
  });

  const errorStatus = isAxiosError(sharedFolderQuery.error)
    ? sharedFolderQuery.error.response?.status
    : undefined;

  return (
    <main className="min-h-screen bg-otter-50 text-gray-800">
      <header className="border-b border-gray-300 bg-white">
        <div className="mx-auto flex h-14 max-w-4xl items-center gap-3 px-4">
          <Logo size={30} />
          <span className="font-semibold text-gray-900">OtterWorks</span>
        </div>
      </header>

      <div className="mx-auto max-w-4xl px-4 py-10">
        {sharedFolderQuery.isLoading ? (
          <div className="flex min-h-64 items-center justify-center text-otter-600">
            <Loader2 className="animate-spin" size={28} />
          </div>
        ) : errorStatus === 410 ? (
          <StatusMessage icon={Clock} title="This link has expired" />
        ) : errorStatus === 404 ? (
          <StatusMessage title="Link not found or revoked" />
        ) : sharedFolderQuery.isError ? (
          <StatusMessage title="Unable to load this shared folder" />
        ) : sharedFolderQuery.data ? (
          <div className="space-y-6">
            <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
              <div className="flex items-start gap-4">
                <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-amber-50">
                  <Folder size={30} className="text-amber-600" />
                </div>
                <div>
                  <h1 className="text-2xl font-bold text-gray-900">
                    {sharedFolderQuery.data.folder.name}
                  </h1>
                  <p className="mt-1 text-sm text-gray-500">
                    Shared folder · link expires{" "}
                    {new Date(sharedFolderQuery.data.expiresAt).toLocaleString()}
                  </p>
                </div>
              </div>
            </div>

            <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
              {sharedFolderQuery.data.files.length ? (
                <div className="divide-y divide-gray-100">
                  {sharedFolderQuery.data.files.map((file) => (
                    <div key={file.id} className="flex items-center gap-3 px-5 py-4">
                      <FileText size={20} className="shrink-0 text-otter-600" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-gray-900">{file.name}</p>
                        <p className="mt-0.5 text-xs text-gray-500">
                          {formatFileSize(file.size)} · Updated {formatRelativeTime(file.updatedAt)}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="px-5 py-10 text-center text-sm text-gray-500">
                  This folder has no files.
                </p>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </main>
  );
}

function StatusMessage({
  icon: Icon = FileText,
  title,
}: {
  icon?: LucideIcon;
  title: string;
}) {
  return (
    <div className="flex min-h-64 flex-col items-center justify-center gap-3 text-center">
      <Icon size={34} className="text-gray-400" />
      <h1 className="text-xl font-semibold text-gray-900">{title}</h1>
    </div>
  );
}
