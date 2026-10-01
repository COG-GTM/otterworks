import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, useRef, useCallback, useEffect } from "react";
import {
  ArrowLeft,
  Share2,
  Trash2,
  Save,
  Clock,
  Users,
  Copy,
  Check,
  X,
} from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { Breadcrumb } from "@/components/layout/breadcrumb";
import { CollaborativeEditor } from "@/components/editor/collaborative-editor";
import { UserPresenceAvatars } from "@/components/editor/user-presence-avatars";
import { PageLoader } from "@/components/ui/loading-spinner";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { documentsApi } from "@/lib/api";
import { formatRelativeTime } from "@/lib/utils";

export default function DocumentEditorPage() {
  return (
    <AppShell>
      <ErrorBoundary>
        <DocumentEditorContent />
      </ErrorBoundary>
    </AppShell>
  );
}

function DocumentEditorContent() {
  const params = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const documentId = params.id as string;
  const [title, setTitle] = useState("");
  const [isTitleEditing, setIsTitleEditing] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [shareEmail, setShareEmail] = useState("");
  const [shareCopied, setShareCopied] = useState(false);
  const [shareStatus, setShareStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [hasContent, setHasContent] = useState(false);
  const latestContentRef = useRef<string | null>(null);
  const documentIdRef = useRef(documentId);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  documentIdRef.current = documentId;

  const { data: document, isLoading } = useQuery({
    queryKey: ["documents", documentId],
    queryFn: () => documentsApi.get(documentId),
  });

  const updateMutation = useMutation({
    mutationFn: (updates: { title?: string; content?: string }) =>
      documentsApi.update(documentId, updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents", documentId] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => documentsApi.delete(documentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      navigate("/documents");
    },
  });

  useEffect(() => {
    if (document?.content && latestContentRef.current === null) {
      latestContentRef.current = document.content;
      setHasContent(true);
    }
  }, [document]);

  const debouncedSave = useCallback(
    (content: string) => {
      latestContentRef.current = content;
      if (!hasContent) setHasContent(true);
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(() => {
        saveTimerRef.current = null;
        updateMutation.mutate({ content });
      }, 1000);
    },
    [updateMutation, hasContent]
  );

  useEffect(() => {
    return () => {
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
        if (latestContentRef.current !== null) {
          documentsApi.update(documentIdRef.current, { content: latestContentRef.current }).catch(() => {});
        }
      }
    };
  }, []);

  if (isLoading) return <PageLoader />;
  if (!document) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px]">
        <p className="text-slate-400">Document not found</p>
        <Link to="/documents" className="text-otter-300 hover:text-otter-200 hover:underline mt-2 text-sm">
          Back to documents
        </Link>
      </div>
    );
  }

  const displayTitle = isTitleEditing ? title : document.title;

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      <Breadcrumb
        items={[
          { label: "Documents", href: "/documents" },
          { label: document.title },
        ]}
      />

      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3 flex-1 min-w-0">
          <button
            onClick={() => navigate(-1)}
            className="p-2 rounded-lg hover:bg-surface-raised text-slate-400 hover:text-slate-200 flex-shrink-0"
          >
            <ArrowLeft size={20} />
          </button>
          {isTitleEditing ? (
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onBlur={() => {
                if (title.trim() && title !== document.title) {
                  updateMutation.mutate({ title: title.trim() });
                }
                setIsTitleEditing(false);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  (e.target as HTMLInputElement).blur();
                }
              }}
              className="text-xl font-bold text-slate-100 bg-transparent border-b-2 border-otter-400 outline-none flex-1 min-w-0"
              autoFocus
            />
          ) : (
            <h1 className="text-xl font-bold truncate">
              <button
                type="button"
                className="text-slate-100 cursor-pointer hover:text-otter-300 truncate bg-transparent border-0 p-0 text-left"
                onClick={() => {
                  setTitle(document.title);
                  setIsTitleEditing(true);
                }}
                title="Click to rename"
              >
                {displayTitle}
              </button>
            </h1>
          )}
        </div>

        <div className="flex items-center gap-3">
          {/* Collaborators */}
          {(document.collaborators ?? []).length > 0 && (
            <UserPresenceAvatars collaborators={document.collaborators} />
          )}

          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
                if (latestContentRef.current !== null) {
                  updateMutation.mutate({ content: latestContentRef.current });
                }
              }}
              disabled={updateMutation.isPending || !hasContent}
              className="flex items-center gap-1.5 px-3 py-2 text-sm text-slate-300 bg-surface-raised border border-line rounded-lg hover:bg-surface-hover hover:text-slate-100 disabled:opacity-50 transition"
            >
              <Save size={16} />
              Save
            </button>
            <button
              onClick={() => setShareOpen(!shareOpen)}
              className="flex items-center gap-1.5 px-3 py-2 text-sm text-slate-300 bg-surface-raised border border-line rounded-lg hover:bg-surface-hover hover:text-slate-100 disabled:opacity-50 transition"
            >
              <Share2 size={16} />
              Share
            </button>
            <button
              onClick={() => deleteMutation.mutate()}
              className="flex items-center gap-1.5 px-3 py-2 text-sm text-red-400 bg-surface-raised border border-red-500/30 rounded-lg hover:bg-red-500/10 transition"
            >
              <Trash2 size={16} />
            </button>
          </div>
        </div>
      </div>

      {/* Meta info */}
      <div className="flex items-center gap-4 text-xs text-slate-500">
        <span className="flex items-center gap-1">
          <Clock size={12} />
          Last edited {formatRelativeTime(document.updatedAt)}
        </span>
        <span className="flex items-center gap-1">
          <Users size={12} />
          {(document.collaborators ?? []).filter((c) => c.isOnline).length} online
        </span>
        {document.wordCount > 0 && (
          <span>{document.wordCount} words</span>
        )}
      </div>

      {/* Share dialog */}
      {shareOpen && (
        <div className="bg-surface rounded-xl border border-line p-5 space-y-4 shadow-sm shadow-black/40">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-100">Share document</h3>
            <button onClick={() => setShareOpen(false)} className="p-1 rounded hover:bg-surface-raised text-slate-500 hover:text-slate-300">
              <X size={16} />
            </button>
          </div>
          <div className="flex gap-2">
            <input
              type="email"
              value={shareEmail}
              onChange={(e) => setShareEmail(e.target.value)}
              placeholder="Enter email address"
              className="flex-1 px-3 py-2 bg-surface-raised border border-line rounded-lg text-sm text-slate-100 placeholder:text-slate-500 hover:border-line-strong focus:outline-none focus:ring-2 focus:ring-otter-400"
              onKeyDown={(e) => {
                if (e.key === "Enter" && shareEmail.trim() && shareStatus !== "sending") {
                  setShareStatus("sending");
                  documentsApi.share(documentId, [{ userId: "", name: "", email: shareEmail.trim(), permission: "edit" }])
                    .then(() => { setShareStatus("sent"); setShareEmail(""); setTimeout(() => setShareStatus("idle"), 2000); })
                    .catch(() => { setShareStatus("error"); setTimeout(() => setShareStatus("idle"), 3000); });
                }
              }}
            />
            <button
              onClick={() => {
                if (shareEmail.trim()) {
                  setShareStatus("sending");
                  documentsApi.share(documentId, [{ userId: "", name: "", email: shareEmail.trim(), permission: "edit" }])
                    .then(() => { setShareStatus("sent"); setShareEmail(""); setTimeout(() => setShareStatus("idle"), 2000); })
                    .catch(() => { setShareStatus("error"); setTimeout(() => setShareStatus("idle"), 3000); });
                }
              }}
              disabled={shareStatus === "sending"}
              className="px-4 py-2 bg-otter-500 text-white rounded-lg text-sm hover:bg-otter-400 transition disabled:opacity-50"
            >
              {shareStatus === "sending" ? "Sending..." : "Invite"}
            </button>
          </div>
          {shareStatus === "sent" && (
            <p className="text-sm text-green-400">Invite sent successfully</p>
          )}
          {shareStatus === "error" && (
            <p className="text-sm text-red-400">Failed to send invite. Please try again.</p>
          )}
          <div className="flex items-center gap-2 pt-2 border-t border-line">
            <button
              onClick={() => {
                navigator.clipboard.writeText(window.location.href);
                setShareCopied(true);
                setTimeout(() => setShareCopied(false), 2000);
              }}
              className="flex items-center gap-1.5 px-3 py-2 text-sm text-slate-300 bg-surface-raised rounded-lg hover:bg-surface-hover hover:text-slate-100 transition"
            >
              {shareCopied ? <Check size={14} /> : <Copy size={14} />}
              {shareCopied ? "Copied!" : "Copy link"}
            </button>
          </div>
        </div>
      )}

      {/* Editor */}
      <CollaborativeEditor
        key={documentId}
        documentId={documentId}
        initialContent={document.content}
        onUpdate={debouncedSave}
      />
    </div>
  );
}
