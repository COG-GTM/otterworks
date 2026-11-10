import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Folder, File, Clock, AlertCircle, LinkIcon } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { LoadingSpinner } from "@/components/ui/loading-spinner";
import { folderShareLinksApi } from "@/lib/api";
import { formatFileSize, formatRelativeTime } from "@/lib/utils";

export const LINK_EXPIRED_MESSAGE = "This link has expired, ask the owner for a new one";

export default function SharedFolderPage() {
  const { token = "" } = useParams<{ token: string }>();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["shared-folder", token],
    queryFn: () => folderShareLinksApi.openShared(token),
    enabled: token.length > 0,
    retry: false,
  });

  return (
    <div className="min-h-screen bg-otter-50 flex flex-col">
      <header className="bg-white border-b border-gray-300 h-14 flex items-center px-4">
        <Link to="/" aria-label="OtterWorks home">
          <Logo />
        </Link>
      </header>
      <main className="flex-1 w-full max-w-4xl mx-auto px-4 py-8">
        {isLoading ? (
          <div className="flex justify-center py-16">
            <LoadingSpinner />
          </div>
        ) : !token || data?.status === "not_found" ? (
          <Notice
            icon={LinkIcon}
            title="Link not found"
            description="This share link is not valid. Check that you copied the full link."
          />
        ) : data?.status === "gone" ? (
          <Notice icon={Clock} title={LINK_EXPIRED_MESSAGE} />
        ) : isError || !data ? (
          <Notice
            icon={AlertCircle}
            title="Something went wrong"
            description="The shared folder could not be loaded. Try again in a moment."
          />
        ) : (
          <section className="bg-white rounded-xl border border-gray-200">
            <div className="flex items-center justify-between gap-4 px-5 py-4 border-b border-gray-200">
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-10 h-10 rounded-lg bg-amber-50 flex items-center justify-center flex-shrink-0">
                  <Folder size={20} className="text-amber-600" />
                </div>
                <h1 className="text-lg font-semibold text-gray-900 truncate">{data.data.folder.name}</h1>
              </div>
              <p className="text-xs text-gray-500 whitespace-nowrap">
                View only &middot; link expires {new Date(data.data.expiresAt).toLocaleDateString()}
              </p>
            </div>
            {data.data.files.length === 0 ? (
              <p className="text-sm text-gray-500 text-center py-10">This folder is empty</p>
            ) : (
              <ul className="divide-y divide-gray-100">
                {data.data.files.map((file) => (
                  <li key={file.id} className="flex items-center gap-4 px-5 py-3">
                    <File size={18} className="text-gray-400 flex-shrink-0" />
                    <span className="flex-1 text-sm text-gray-900 truncate">{file.name}</span>
                    <span className="text-xs text-gray-500 w-32 hidden sm:block truncate">
                      {formatRelativeTime(file.updatedAt)}
                    </span>
                    <span className="text-xs text-gray-500 w-20 text-right">
                      {formatFileSize(file.size ?? 0)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </main>
    </div>
  );
}

function Notice({
  icon: Icon,
  title,
  description,
}: Readonly<{ icon: typeof Clock; title: string; description?: string }>) {
  return (
    <div role="status" className="bg-white rounded-xl border border-gray-200 px-6 py-12 text-center">
      <div className="mx-auto mb-4 w-12 h-12 rounded-full bg-otter-100 flex items-center justify-center">
        <Icon size={22} className="text-otter-600" />
      </div>
      <h1 className="text-lg font-semibold text-gray-900">{title}</h1>
      {description && <p className="mt-2 text-sm text-gray-500">{description}</p>}
    </div>
  );
}
