import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Eye } from "lucide-react";
import { shareLinksApi } from "@/lib/api";
import { formatRelativeTime } from "@/lib/utils";
import { PageLoader } from "@/components/ui/loading-spinner";
import { SharedLinkLayout } from "@/components/sharing/shared-link-layout";
import { ReadOnlyDocument } from "@/components/sharing/read-only-document";
import { retryTransient, ShareLinkFailure } from "@/pages/shared-folder";

export default function SharedFolderDocumentPage() {
  const { token = "", documentId = "" } = useParams<{ token: string; documentId: string }>();
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ["shared-folder", token, "documents", documentId],
    queryFn: () => shareLinksApi.getSharedDocument(token, documentId),
    retry: retryTransient,
  });

  return (
    <SharedLinkLayout>
      {isLoading ? (
        <PageLoader />
      ) : error ? (
        <ShareLinkFailure error={error} onRetry={() => refetch()} />
      ) : data ? (
        <article className="space-y-4">
          <Link
            to={`/shared-folder/${encodeURIComponent(token)}`}
            className="inline-flex items-center gap-1 text-sm text-otter-600 hover:underline"
          >
            <ArrowLeft size={14} /> Back to folder
          </Link>
          <div className="flex items-start justify-between gap-4">
            <h1 className="text-2xl font-bold text-gray-900">{data.title || "Untitled"}</h1>
            <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-100 text-xs font-medium text-gray-600 flex-shrink-0">
              <Eye size={12} /> Read-only
            </span>
          </div>
          {data.updatedAt && (
            <p className="text-xs text-gray-500">Last updated {formatRelativeTime(data.updatedAt)}</p>
          )}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <ReadOnlyDocument content={data.content ?? ""} contentType={data.contentType} />
          </div>
        </article>
      ) : null}
    </SharedLinkLayout>
  );
}
