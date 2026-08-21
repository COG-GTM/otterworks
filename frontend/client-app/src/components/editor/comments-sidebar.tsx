import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  MessageSquare,
  RotateCcw,
  Send,
} from "lucide-react";
import { commentsApi } from "@/lib/api";
import { formatRelativeTime } from "@/lib/utils";
import type { Comment } from "@/types";

interface CommentsSidebarProps {
  documentId: string;
}

export function CommentsSidebar({ documentId }: CommentsSidebarProps) {
  const queryClient = useQueryClient();
  const [content, setContent] = useState("");
  const [showResolved, setShowResolved] = useState(false);
  const commentsQuery = useQuery({
    queryKey: ["comments", documentId],
    queryFn: () => commentsApi.listComments(documentId),
  });

  const invalidateComments = () => {
    queryClient.invalidateQueries({ queryKey: ["comments", documentId] });
  };

  const addMutation = useMutation({
    mutationFn: () => commentsApi.addComment(documentId, content.trim()),
    onSuccess: () => {
      setContent("");
      invalidateComments();
    },
  });

  const resolveMutation = useMutation({
    mutationFn: (commentId: string) => commentsApi.resolveComment(documentId, commentId),
    onSuccess: invalidateComments,
  });

  const unresolveMutation = useMutation({
    mutationFn: (commentId: string) => commentsApi.unresolveComment(documentId, commentId),
    onSuccess: invalidateComments,
  });

  const comments = commentsQuery.data ?? [];
  const openComments = comments.filter((comment) => !comment.isResolved);
  const resolvedComments = comments.filter((comment) => comment.isResolved);
  const isMutating = resolveMutation.isPending || unresolveMutation.isPending;

  return (
    <aside className="w-full lg:w-80 lg:flex-shrink-0 bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <MessageSquare size={17} className="text-otter-600" />
          <h2 className="text-sm font-semibold text-gray-900">Comments</h2>
        </div>
        <span className="text-xs text-gray-400">{openComments.length} open</span>
      </div>

      <div className="max-h-[min(60vh,520px)] overflow-y-auto p-3 space-y-3">
        {commentsQuery.isLoading && (
          <p className="px-1 py-4 text-sm text-gray-500">Loading comments...</p>
        )}
        {commentsQuery.isError && (
          <p className="px-1 py-4 text-sm text-red-600">
            Unable to load comments. Please try again.
          </p>
        )}
        {!commentsQuery.isLoading && !commentsQuery.isError && openComments.length === 0 && (
          <p className="px-1 py-4 text-sm text-gray-500">No open comments.</p>
        )}
        {openComments.map((comment) => (
          <CommentItem
            key={comment.id}
            comment={comment}
            isMutating={isMutating}
            onResolve={() => resolveMutation.mutate(comment.id)}
          />
        ))}

        {resolvedComments.length > 0 && (
          <div className="border-t border-gray-100 pt-2">
            <button
              type="button"
              onClick={() => setShowResolved(!showResolved)}
              className="flex w-full items-center gap-1 px-1 py-2 text-xs font-medium text-gray-500 hover:text-gray-700"
            >
              {showResolved ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              Resolved ({resolvedComments.length})
            </button>
            {showResolved && (
              <div className="space-y-3 pt-1">
                {resolvedComments.map((comment) => (
                  <CommentItem
                    key={comment.id}
                    comment={comment}
                    isMutating={isMutating}
                    onResolve={() => unresolveMutation.mutate(comment.id)}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <form
        className="border-t border-gray-100 p-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (content.trim() && !addMutation.isPending) addMutation.mutate();
        }}
      >
        <textarea
          value={content}
          onChange={(event) => setContent(event.target.value)}
          placeholder="Add a comment..."
          rows={3}
          className="w-full resize-none rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-otter-500 focus:ring-2 focus:ring-otter-100"
        />
        {addMutation.isError && (
          <p className="mt-1 text-xs text-red-600">Unable to add comment.</p>
        )}
        <button
          type="submit"
          disabled={!content.trim() || addMutation.isPending}
          className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg bg-otter-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-otter-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Send size={14} />
          {addMutation.isPending ? "Adding..." : "Add comment"}
        </button>
      </form>
    </aside>
  );
}

interface CommentItemProps {
  comment: Comment;
  isMutating: boolean;
  onResolve: () => void;
}

function CommentItem({ comment, isMutating, onResolve }: CommentItemProps) {
  return (
    <article
      className={`rounded-lg border p-3 ${
        comment.isResolved ? "border-gray-100 bg-gray-50 opacity-60" : "border-gray-200"
      }`}
    >
      <div className="flex items-center justify-between gap-2 text-xs text-gray-500">
        <span className="truncate font-medium text-gray-700" title={comment.authorId}>
          {comment.authorId}
        </span>
        <span className="flex-shrink-0">{formatRelativeTime(comment.createdAt)}</span>
      </div>
      <p className="mt-2 whitespace-pre-wrap break-words text-sm text-gray-700">
        {comment.content}
      </p>
      <button
        type="button"
        onClick={onResolve}
        disabled={isMutating}
        className="mt-3 flex items-center gap-1 text-xs font-medium text-otter-700 hover:text-otter-900 disabled:opacity-50"
      >
        {comment.isResolved ? <RotateCcw size={13} /> : <CheckCircle2 size={13} />}
        {comment.isResolved ? "Unresolve" : "Resolve"}
      </button>
    </article>
  );
}
