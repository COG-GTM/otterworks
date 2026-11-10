import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Clock, Eye, FileText, LinkIcon } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { shareLinksApi } from "@/lib/api";
import { formatRelativeTime } from "@/lib/utils";

function Shell({ children }: Readonly<{ children: React.ReactNode }>) {
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
}: Readonly<{ icon: typeof Clock; title: string; children: React.ReactNode }>) {
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

function InvalidLink() {
  return (
    <Notice icon={LinkIcon} title="This link is not valid">
      <p>Check that you copied the whole link, or ask the document owner for a new one.</p>
    </Notice>
  );
}

function ReadOnlyContent({ content }: Readonly<{ content: string }>) {
  const editor = useEditor({
    extensions: [StarterKit],
    content,
    editable: false,
  });
  return (
    <EditorContent
      editor={editor}
      className="prose prose-sm max-w-none px-6 py-5"
      data-testid="shared-document-content"
    />
  );
}

export default function SharedDocumentPage() {
  const { documentId = "" } = useParams<{ documentId: string }>();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const hasLink = !!documentId && !!token;

  const { data, error, isLoading } = useQuery({
    queryKey: ["shared-document", documentId, token],
    queryFn: () => shareLinksApi.openShared(documentId, token),
    retry: false,
    enabled: hasLink,
  });

  if (!hasLink) {
    return (
      <Shell>
        <InvalidLink />
      </Shell>
    );
  }

  if (isLoading) {
    return (
      <Shell>
        <p className="text-sm text-gray-500 text-center">Opening shared document...</p>
      </Shell>
    );
  }

  if (error) {
    const status = isAxiosError(error) ? error.response?.status : undefined;
    let body: React.ReactNode;
    if (status === 410) {
      body = (
        <Notice icon={Clock} title="This link has expired">
          <p>Share links stop working after their expiry date.</p>
          <p>Ask the document owner to send you a new link.</p>
        </Notice>
      );
    } else if (status === 403) {
      body = <InvalidLink />;
    } else if (status === 401) {
      body = (
        <Notice icon={LinkIcon} title="Sign in to open this link">
          <p>Shared documents open for signed-in OtterWorks users.</p>
        </Notice>
      );
    } else if (status === 404) {
      body = (
        <Notice icon={LinkIcon} title="Document not found">
          <p>This document may have been deleted. Ask the owner for a new link.</p>
        </Notice>
      );
    } else {
      body = (
        <Notice icon={LinkIcon} title="We couldn't open this link">
          <p>Please try again in a moment.</p>
        </Notice>
      );
    }
    return <Shell>{body}</Shell>;
  }

  if (!data) return null;

  return (
    <Shell>
      <article className="bg-white border border-gray-200 rounded-2xl">
        <div className="flex items-center gap-3 px-6 py-5 border-b border-gray-200">
          <div className="w-10 h-10 rounded-lg bg-otter-50 flex items-center justify-center">
            <FileText size={20} className="text-otter-600" />
          </div>
          <div className="flex-1 min-w-0">
            <h1 className="text-lg font-semibold text-gray-900 truncate">{data.title}</h1>
            {data.updatedAt && (
              <p className="text-xs text-gray-500">Last edited {formatRelativeTime(data.updatedAt)}</p>
            )}
          </div>
          <span className="flex items-center gap-1 text-xs text-gray-600 px-2 py-1 bg-gray-100 rounded-full">
            <Eye size={12} />
            View only
          </span>
        </div>
        {data.content ? (
          <ReadOnlyContent content={data.content} />
        ) : (
          <p className="px-6 py-10 text-sm text-gray-500 text-center">This document is empty</p>
        )}
      </article>
    </Shell>
  );
}
