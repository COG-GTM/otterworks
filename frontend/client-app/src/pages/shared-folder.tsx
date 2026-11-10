import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { FileText, Eye, Clock, FolderOpen } from "lucide-react";
import { shareLinksApi } from "@/lib/api";
import { errorDetail, errorStatus, formatExpiresAt } from "@/lib/share-links";
import { formatRelativeTime } from "@/lib/utils";
import { PageLoader } from "@/components/ui/loading-spinner";
import { EmptyState } from "@/components/ui/empty-state";
import {
  SharedLinkLayout,
  ShareLinkError,
  ShareLinkExpired,
  ShareLinkNotFound,
} from "@/components/sharing/shared-link-layout";

// 4xx answers (expired, revoked, unknown token) are final; only retry transient failures.
export function retryTransient(failureCount: number, err: unknown): boolean {
  const status = errorStatus(err);
  return !(status && status >= 400 && status < 500) && failureCount < 1;
}

/** Renders the expired / not-found / error page for a failed share-link query, else null. */
export function ShareLinkFailure({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const status = errorStatus(error);
  if (status === 410) return <ShareLinkExpired detail={errorDetail(error)} />;
  if (status === 404) return <ShareLinkNotFound />;
  return <ShareLinkError onRetry={onRetry} />;
}

export default function SharedFolderPage() {
  const { token = "" } = useParams<{ token: string }>();
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["shared-folder", token],
    queryFn: () => shareLinksApi.getSharedFolder(token),
    retry: retryTransient,
  });

  return (
    <SharedLinkLayout>
      {isLoading ? (
        <PageLoader />
      ) : error ? (
        <ShareLinkFailure error={error} onRetry={() => refetch()} />
      ) : data ? (
        <div className="space-y-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Shared folder</h1>
            <p className="mt-1 flex flex-wrap items-center gap-3 text-sm text-gray-500">
              <span className="flex items-center gap-1">
                <Eye size={14} /> View only
              </span>
              <span className="flex items-center gap-1">
                <Clock size={14} /> {formatExpiresAt(data.expiresAt)}
              </span>
            </p>
          </div>
          {data.documents.length === 0 ? (
            <EmptyState icon={FolderOpen} title="This folder has no documents" />
          ) : (
            <ul className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
              {data.documents.map((doc) => (
                <li key={doc.id}>
                  <Link
                    to={`/shared-folder/${encodeURIComponent(token)}/documents/${doc.id}`}
                    className="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition"
                  >
                    <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center flex-shrink-0">
                      <FileText size={18} className="text-blue-600" />
                    </div>
                    <span className="flex-1 min-w-0 text-sm font-medium text-gray-900 truncate">
                      {doc.title || "Untitled"}
                    </span>
                    <span className="text-xs text-gray-500">{formatRelativeTime(doc.updatedAt)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </SharedLinkLayout>
  );
}
