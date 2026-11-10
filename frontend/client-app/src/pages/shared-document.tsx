import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { Clock, Lock } from "lucide-react";
import { PageLoader } from "@/components/ui/loading-spinner";
import { documentsApi } from "@/lib/api";

function Notice({ title, message }: { title: string; message: string }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 px-6 text-center">
      <h1 className="text-2xl font-semibold text-gray-900">{title}</h1>
      <p className="max-w-md text-sm text-gray-600">{message}</p>
      <Link to="/" className="text-otter-600 hover:underline">
        Go to OtterWorks
      </Link>
    </div>
  );
}

export default function SharedDocumentPage() {
  const { documentId = "" } = useParams();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";

  const { data, error, isLoading } = useQuery({
    queryKey: ["shared-document", documentId, token],
    queryFn: () => documentsApi.getShared(documentId, token),
    enabled: Boolean(documentId && token),
    retry: false,
  });

  if (!token) {
    return <Notice title="Invalid link" message="This share link is missing its access token." />;
  }
  if (isLoading) return <PageLoader />;
  if (error) {
    const status = isAxiosError(error) ? error.response?.status : undefined;
    if (status === 410) {
      return (
        <div data-testid="share-link-expired">
          <Notice
            title="This link has expired"
            message="The owner set this share link to expire. Ask them to send you a new link."
          />
        </div>
      );
    }
    return <Notice title="Link not available" message="This share link is invalid or has been removed." />;
  }
  if (!data) return null;

  return (
    <div className="mx-auto max-w-3xl space-y-4 px-6 py-10">
      <div className="flex items-center gap-2 text-xs text-gray-500">
        <Lock size={12} /> Read-only shared document
        <Clock size={12} className="ml-3" /> Last edited {new Date(data.updatedAt).toLocaleString()}
      </div>
      <h1 className="text-3xl font-semibold text-gray-900">{data.title}</h1>
      <article className="prose max-w-none whitespace-pre-wrap text-gray-800">{data.content}</article>
    </div>
  );
}
