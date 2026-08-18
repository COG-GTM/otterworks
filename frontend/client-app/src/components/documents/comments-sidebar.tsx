import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  MessageSquare,
  Check,
  ChevronDown,
  ChevronRight,
  RotateCcw,
  Send,
  X,
} from "lucide-react";
import type { Comment } from "@/types";
import { documentsApi } from "@/lib/api";
import { cn, formatRelativeTime } from "@/lib/utils";
import { LoadingSpinner } from "@/components/ui/loading-spinner";

interface CommentsSidebarProps {
  documentId: string;
  onClose?: () => void;
}

export function CommentsSidebar({ documentId, onClose }: CommentsSidebarProps) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [resolvedOpen, setResolvedOpen] = useState(false);

  const {
    data: comments,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["document-comments", documentId],
    queryFn: () => documentsApi.listComments(documentId, true),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["document-comments", documentId] });
  };

  const addMutation = useMutation({
    mutationFn: (content: string) => documentsApi.addComment(documentId, content),
    onSuccess: () => {
      setDraft("");
      invalidate();
    },
  });

  const resolveMutation = useMutation({
    mutationFn: ({ commentId, resolved }: { commentId: string; resolved: boolean }) =>
      resolved
        ? documentsApi.resolveComment(documentId, commentId)
        : documentsApi.unresolveComment(documentId, commentId),
    onSuccess: invalidate,
  });

  const open = (comments ?? []).filter((c) => !c.isResolved);
  const resolved = (comments ?? []).filter((c) => c.isResolved);

  const handleSubmit = () => {
    const content = draft.trim();
    if (!content || addMutation.isPending) return;
    addMutation.mutate(content);
  };

  return (
    <aside
      aria-label="Comments"
      className="w-full lg:w-80 flex-shrink-0 bg-white border border-gray-200 rounded-lg flex flex-col self-start"
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-900">
          <MessageSquare size={16} className="text-otter-600" />
          Comments
        </h2>
        {onClose && (
          <button
            onClick={onClose}
            aria-label="Close comments"
            className="p-1 rounded hover:bg-gray-100 text-gray-400"
          >
            <X size={16} />
          </button>
        )}
      </div>

      <div className="px-4 py-3 border-b border-gray-100 space-y-2">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Add a comment"
          aria-label="Add a comment"
          rows={3}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-otter-500"
        />
        <div className="flex items-center justify-end">
          <button
            onClick={handleSubmit}
            disabled={!draft.trim() || addMutation.isPending}
            className="flex items-center gap-1.5 px-3 py-2 bg-otter-600 text-white rounded-lg text-sm hover:bg-otter-700 transition disabled:opacity-50"
          >
            <Send size={14} />
            {addMutation.isPending ? "Posting..." : "Comment"}
          </button>
        </div>
        {addMutation.isError && (
          <p className="text-sm text-red-600">Failed to add comment. Please try again.</p>
        )}
      </div>

      {resolveMutation.isError && (
        <p className="px-4 py-2 text-sm text-red-600">
          Failed to update comment. Please try again.
        </p>
      )}

      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="py-8 flex justify-center">
            <LoadingSpinner />
          </div>
        ) : isError ? (
          <p className="px-4 py-6 text-sm text-red-600">Failed to load comments.</p>
        ) : open.length === 0 && resolved.length === 0 ? (
          <p className="px-4 py-6 text-sm text-gray-500 text-center">No comments yet</p>
        ) : (
          <div className="divide-y divide-gray-100">
            {open.length === 0 && (
              <p className="px-4 py-4 text-sm text-gray-500">No open comments</p>
            )}
            {open.map((comment) => (
              <CommentRow
                key={comment.id}
                comment={comment}
                onToggleResolved={() =>
                  resolveMutation.mutate({ commentId: comment.id, resolved: true })
                }
                isToggling={
                  resolveMutation.isPending &&
                  resolveMutation.variables?.commentId === comment.id
                }
              />
            ))}

            {resolved.length > 0 && (
              <div>
                <button
                  onClick={() => setResolvedOpen((prev) => !prev)}
                  aria-expanded={resolvedOpen}
                  className="w-full flex items-center gap-1.5 px-4 py-3 text-xs font-medium text-gray-500 hover:bg-gray-50 transition"
                >
                  {resolvedOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  Resolved ({resolved.length})
                </button>
                {resolvedOpen && (
                  <div className="divide-y divide-gray-100">
                    {resolved.map((comment) => (
                      <CommentRow
                        key={comment.id}
                        comment={comment}
                        onToggleResolved={() =>
                          resolveMutation.mutate({ commentId: comment.id, resolved: false })
                        }
                        isToggling={
                          resolveMutation.isPending &&
                          resolveMutation.variables?.commentId === comment.id
                        }
                      />
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}

interface CommentRowProps {
  comment: Comment;
  onToggleResolved: () => void;
  isToggling: boolean;
}

function CommentRow({ comment, onToggleResolved, isToggling }: CommentRowProps) {
  return (
    <article
      data-testid={`comment-${comment.id}`}
      className={cn("px-4 py-3 space-y-1", comment.isResolved && "opacity-50")}
    >
      <p className="text-sm text-gray-900 whitespace-pre-wrap break-words">{comment.content}</p>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-gray-400">
          {formatRelativeTime(comment.createdAt)}
        </span>
        <button
          onClick={onToggleResolved}
          disabled={isToggling}
          aria-label={comment.isResolved ? "Unresolve comment" : "Resolve comment"}
          className="flex items-center gap-1 px-2 py-1 text-xs text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition disabled:opacity-50"
        >
          {comment.isResolved ? <RotateCcw size={12} /> : <Check size={12} />}
          {comment.isResolved ? "Unresolve" : "Resolve"}
        </button>
      </div>
    </article>
  );
}
