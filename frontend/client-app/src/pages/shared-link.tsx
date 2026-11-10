import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { Clock, Eye, FileText, Folder, LinkIcon } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { shareLinksApi } from "@/lib/api";
import { formatFileSize, formatRelativeTime } from "@/lib/utils";
import { formatExpiry } from "@/components/files/folder-share-link-panel";

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="flex items-center gap-2 px-6 py-4 bg-white border-b border-gray-200">
        <Logo size={28} />
        <span className="text-lg font-semibold text-gray-900">OtterWorks</span>
      </header>
      <main className="max-w-3xl mx-auto px-4 py-10">{children}</main>
    </div>
  );
}

function Notice({
  icon: Icon,
  title,
  children,
}: {
  icon: typeof Clock;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center text-center gap-3 bg-white border border-gray-200 rounded-2xl px-6 py-12">
      <div className="w-12 h-12 rounded-full bg-amber-50 flex items-center justify-center">
        <Icon size={24} className="text-amber-600" />
      </div>
      <h1 className="text-xl font-semibold text-gray-900">{title}</h1>
      <div className="text-sm text-gray-600 max-w-md space-y-1">{children}</div>
      <Link to="/" className="mt-2 text-sm text-otter-600 hover:underline">
        Go to OtterWorks
      </Link>
    </div>
  );
}

export default function SharedLinkPage() {
  const { token = "" } = useParams<{ token: string }>();
  const { data, error, isLoading } = useQuery({
    queryKey: ["share-link-resolve", token],
    queryFn: () => shareLinksApi.resolve(token),
    retry: false,
    enabled: !!token,
  });

  if (isLoading) {
    return (
      <Shell>
        <p className="text-sm text-gray-500 text-center">Opening shared folder…</p>
      </Shell>
    );
  }

  if (error) {
    const status = isAxiosError(error) ? error.response?.status : undefined;
    if (status === 410) {
      const expiredAt = (error as { response?: { data?: { expired_at?: string; expiredAt?: string } } })
        .response?.data;
      const when = expiredAt?.expiredAt ?? expiredAt?.expired_at;
      return (
        <Shell>
          <Notice icon={Clock} title="This link has expired">
            <p>Ask the owner of this folder to share it with you again.</p>
            {when && <p className="text-xs text-gray-500">Expired on {formatExpiry(when)}</p>}
          </Notice>
        </Shell>
      );
    }
    if (status === 404) {
      return (
        <Shell>
          <Notice icon={LinkIcon} title="Link not found">
            <p>Check the address, or ask the owner of the folder for a new link.</p>
          </Notice>
        </Shell>
      );
    }
    return (
      <Shell>
        <Notice icon={LinkIcon} title="We couldn't open this link">
          <p>Please try again in a moment.</p>
        </Notice>
      </Shell>
    );
  }

  if (!data) return null;

  return (
    <Shell>
      <div className="bg-white border border-gray-200 rounded-2xl">
        <div className="flex items-center gap-3 px-6 py-5 border-b border-gray-200">
          <div className="w-10 h-10 rounded-lg bg-amber-50 flex items-center justify-center">
            <Folder size={20} className="text-amber-600" />
          </div>
          <div className="flex-1 min-w-0">
            <h1 className="text-lg font-semibold text-gray-900 truncate">{data.folder.name}</h1>
            {data.expiresAt && (
              <p className="text-xs text-gray-500">Link expires on {formatExpiry(data.expiresAt)}</p>
            )}
          </div>
          <span className="flex items-center gap-1 text-xs text-gray-600 px-2 py-1 bg-gray-100 rounded-full">
            <Eye size={12} />
            View only
          </span>
        </div>
        {data.files.length === 0 ? (
          <p className="px-6 py-10 text-sm text-gray-500 text-center">This folder is empty</p>
        ) : (
          <ul aria-label="Shared files" className="divide-y divide-gray-100">
            {data.files.map((file) => (
              <li key={file.id} className="flex items-center gap-4 px-6 py-3">
                <FileText size={18} className="text-gray-400 flex-shrink-0" />
                <span className="flex-1 min-w-0 text-sm text-gray-900 truncate">{file.name}</span>
                <span className="text-xs text-gray-500 w-24 hidden sm:block">
                  {file.updatedAt ? formatRelativeTime(file.updatedAt) : ""}
                </span>
                <span className="text-xs text-gray-400 w-16 text-right">{formatFileSize(file.size)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Shell>
  );
}
