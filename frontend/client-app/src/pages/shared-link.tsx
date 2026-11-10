import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { PageLoader } from "@/components/ui/loading-spinner";
import { documentsApi } from "@/lib/api";

function ReadOnlyContent({ html }: { html: string }) {
  const editor = useEditor(
    { extensions: [StarterKit], content: html, editable: false },
    [html],
  );
  return <EditorContent editor={editor} className="prose mt-6 max-w-none text-gray-800" />;
}

function statusOf(error: unknown): number | undefined {
  return (error as { response?: { status?: number } })?.response?.status;
}

export default function SharedLinkPage() {
  const { documentId = "" } = useParams<{ documentId: string }>();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";

  const { data, error, isLoading } = useQuery({
    queryKey: ["shared-link", documentId, token],
    queryFn: () => documentsApi.getShared(documentId, token),
    enabled: !!documentId && !!token,
    retry: false,
  });

  if (isLoading) return <PageLoader />;

  if (error || !data) {
    const status = statusOf(error);
    const message =
      status === 410
        ? "This share link has expired. Ask the document owner for a new link."
        : "This share link is invalid.";
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-2 px-4">
        <h1 className="text-2xl font-semibold text-gray-900">
          {status === 410 ? "Link expired" : "Link unavailable"}
        </h1>
        <p className="text-gray-600">{message}</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <p className="text-xs uppercase tracking-wide text-gray-400">Shared read-only document</p>
      <h1 className="mt-1 text-3xl font-semibold text-gray-900">{data.title}</h1>
      <ReadOnlyContent html={data.content ?? ""} />
    </div>
  );
}
