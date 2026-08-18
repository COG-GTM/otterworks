import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { CheckCircle2, MessageSquare, RotateCcw, Trash2, X } from "lucide-react";
import { commentsApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";
import { formatRelativeTime } from "@/lib/utils";
import type { DocumentComment } from "@/types";

interface CommentsSidebarProps {
  documentId: string;
  onClose: () => void;
}

export function CommentsSidebar({ documentId, onClose }: CommentsSidebarProps) {
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const [newComment, setNewComment] = useState("");

  const { data: comments = [], isLoading, isError, refetch } = useQuery({
    queryKey: ["document-comments", documentId],
    queryFn: () => commentsApi.list(documentId),
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["document-comments", documentId] });

  const addMutation = useMutation({
    mutationFn: (content: string) => commentsApi.create(documentId, user?.id ?? "", content),
    onSuccess: () => {
      setNewComment("");
      invalidate();
    },
    onError: () => toast.error("Failed to post comment"),
  });

  const resolveMutation = useMutation({
    mutationFn: (commentId: string) => commentsApi.resolve(documentId, commentId, user?.id ?? ""),
    onSuccess: invalidate,
    onError: () => toast.error("Failed to resolve comment"),
  });

  const unresolveMutation = useMutation({
    mutationFn: (commentId: string) => commentsApi.unresolve(documentId, commentId),
    onSuccess: invalidate,
    onError: () => toast.error("Failed to reopen comment"),
  });

  const deleteMutation = useMutation({
    mutationFn: (commentId: string) => commentsApi.delete(documentId, commentId),
    onSuccess: invalidate,
    onError: () => toast.error("Failed to delete comment"),
  });

  const submitComment = () => {
    const content = newComment.trim();
    if (content && user && !addMutation.isPending) {
      addMutation.mutate(content);
    }
  };

  const openComments = comments.filter((c) => !c.isResolved);
  const resolvedComments = comments.filter((c) => c.isResolved);

  return (
    <aside className="w-80 flex-shrink-0 bg-white rounded-xl border border-gray-200 shadow-sm flex flex-col max-h-[70vh]">
      <div className="flex items-center justify-between p-4 border-b border-gray-100">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-900">
          <MessageSquare size={16} />
          Comments
          {comments.length > 0 && (
            <span className="text-xs font-normal text-gray-400">({comments.length})</span>
          )}
        </h3>
        <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 text-gray-400">
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {isLoading ? (
          <p className="text-sm text-gray-400">Loading comments...</p>
        ) : isError ? (
          <div className="space-y-2">
            <p className="text-sm text-red-600">Failed to load comments.</p>
            <button
              onClick={() => refetch()}
              className="text-sm text-otter-600 hover:underline"
            >
              Retry
            </button>
          </div>
        ) : comments.length === 0 ? (
          <p className="text-sm text-gray-400">No comments yet. Start the conversation!</p>
        ) : (
          <>
            {openComments.map((comment) => (
              <CommentCard
                key={comment.id}
                comment={comment}
                onResolve={() => resolveMutation.mutate(comment.id)}
                onUnresolve={() => unresolveMutation.mutate(comment.id)}
                onDelete={() => deleteMutation.mutate(comment.id)}
              />
            ))}
            {resolvedComments.length > 0 && (
              <p className="text-xs font-medium text-gray-400 uppercase tracking-wide pt-2">
                Resolved ({resolvedComments.length})
              </p>
            )}
            {resolvedComments.map((comment) => (
              <CommentCard
                key={comment.id}
                comment={comment}
                onResolve={() => resolveMutation.mutate(comment.id)}
                onUnresolve={() => unresolveMutation.mutate(comment.id)}
                onDelete={() => deleteMutation.mutate(comment.id)}
              />
            ))}
          </>
        )}
      </div>

      <div className="p-4 border-t border-gray-100 space-y-2">
        <textarea
          value={newComment}
          onChange={(e) => setNewComment(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submitComment();
            }
          }}
          placeholder="Add a comment..."
          rows={2}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-otter-500"
        />
        <button
          onClick={submitComment}
          disabled={!newComment.trim() || !user || addMutation.isPending}
          className="w-full px-4 py-2 bg-otter-600 text-white rounded-lg text-sm hover:bg-otter-700 transition disabled:opacity-50"
        >
          {addMutation.isPending ? "Posting..." : "Comment"}
        </button>
      </div>
    </aside>
  );
}

interface CommentCardProps {
  comment: DocumentComment;
  onResolve: () => void;
  onUnresolve: () => void;
  onDelete: () => void;
}

function CommentCard({ comment, onResolve, onUnresolve, onDelete }: CommentCardProps) {
  const [expanded, setExpanded] = useState(false);
  const collapsed = comment.isResolved && !expanded;
  const toggleable = comment.isResolved;

  return (
    <div
      className={`rounded-lg border p-3 space-y-2 transition ${
        comment.isResolved
          ? "border-gray-100 bg-gray-50 opacity-60"
          : "border-gray-200 bg-white"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-gray-400">
          {formatRelativeTime(comment.createdAt)}
          {comment.isResolved && (
            <span className="ml-2 inline-flex items-center gap-1 text-green-600">
              <CheckCircle2 size={12} />
              Resolved
            </span>
          )}
        </span>
        <div className="flex items-center gap-1">
          {comment.isResolved ? (
            <button
              onClick={onUnresolve}
              title="Reopen comment"
              className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600"
            >
              <RotateCcw size={14} />
            </button>
          ) : (
            <button
              onClick={onResolve}
              title="Resolve comment"
              className="p-1 rounded hover:bg-green-50 text-gray-400 hover:text-green-600"
            >
              <CheckCircle2 size={14} />
            </button>
          )}
          <button
            onClick={onDelete}
            title="Delete comment"
            className="p-1 rounded hover:bg-red-50 text-gray-400 hover:text-red-600"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      {toggleable ? (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          title={collapsed ? "Show resolved comment" : "Collapse resolved comment"}
          className={`w-full text-left bg-transparent border-0 p-0 ${
            collapsed
              ? "text-sm text-gray-500 truncate"
              : "text-sm text-gray-700 whitespace-pre-wrap break-words"
          }`}
        >
          {comment.content}
        </button>
      ) : (
        <p className="text-sm text-gray-700 whitespace-pre-wrap break-words">{comment.content}</p>
      )}
    </div>
  );
}
