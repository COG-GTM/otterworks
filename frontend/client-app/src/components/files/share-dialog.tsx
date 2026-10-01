import { useState } from "react";
import { X, Link2, Copy, Check, UserPlus, Globe, Lock, ChevronDown, AlertCircle } from "lucide-react";
import { isAxiosError } from "axios";
import toast from "react-hot-toast";
import { cn } from "@/lib/utils";
import { filesApi } from "@/lib/api";
import type { SharedUser } from "@/types";

interface ShareDialogProps {
  fileId: string;
  fileName: string;
  ownerId?: string;
  ownerName?: string;
  ownerEmail?: string;
  sharedWith: SharedUser[];
  resolvedUsers?: Record<string, { name: string; email: string }>;
  onShare: (email: string, permission: "view" | "edit") => Promise<void>;
  onClose: () => void;
  onPermissionChange?: (userId: string, permission: "view" | "edit") => Promise<void>;
  onRemoveAccess?: (userId: string) => Promise<void>;
}

type LinkAccess = "restricted" | "anyone";

export function ShareDialog({
  fileId,
  fileName,
  ownerId,
  ownerName,
  ownerEmail,
  sharedWith,
  resolvedUsers = {},
  onShare,
  onClose,
  onPermissionChange,
  onRemoveAccess,
}: ShareDialogProps) {
  const [email, setEmail] = useState("");
  const [permission, setPermission] = useState<"view" | "edit">("view");
  const [isSharing, setIsSharing] = useState(false);
  const [copied, setCopied] = useState(false);
  const [activeTab, setActiveTab] = useState<"people" | "link">("people");
  const [linkAccess, setLinkAccess] = useState<LinkAccess>("restricted");
  const [updatingUserId, setUpdatingUserId] = useState<string | null>(null);
  const [removingUserId, setRemovingUserId] = useState<string | null>(null);
  const [shareError, setShareError] = useState<string | null>(null);

  const handleShare = async () => {
    if (!email.trim()) return;
    setIsSharing(true);
    setShareError(null);
    try {
      await onShare(email.trim(), permission);
      setEmail("");
      toast.success(`Shared with ${email.trim()}`);
    } catch (err) {
      let detail = "";
      let isAwsError = false;
      if (isAxiosError(err)) {
        const data = err.response?.data as
          | { error?: string; message?: string }
          | undefined;
        detail = data?.message ?? "";
        isAwsError = data?.error === "event_error" || data?.error === "storage_error";
      }
      const message = detail
        ? isAwsError
          ? `Sharing failed. AWS ${detail}`
          : `Sharing failed: ${detail}`
        : "Sharing failed.";
      setShareError(message);
      toast.error(message);
    } finally {
      setIsSharing(false);
    }
  };

  const handlePermissionChange = async (userId: string, newPermission: "view" | "edit") => {
    setUpdatingUserId(userId);
    try {
      if (onPermissionChange) {
        await onPermissionChange(userId, newPermission);
      } else {
        await filesApi.updateSharePermission(fileId, userId, newPermission);
      }
      toast.success("Permission updated");
    } catch {
      toast.error("Failed to update permission");
    } finally {
      setUpdatingUserId(null);
    }
  };

  const handleRemoveAccess = async (userId: string) => {
    setRemovingUserId(userId);
    try {
      if (onRemoveAccess) {
        await onRemoveAccess(userId);
      } else {
        await filesApi.removeShare(fileId, userId);
      }
      toast.success("Access removed");
    } catch {
      toast.error("Failed to remove access");
    } finally {
      setRemovingUserId(null);
    }
  };

  const handleCopyLink = async () => {
    const shareUrl = `${window.location.origin}/files/${fileId}`;
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      toast.success("Link copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Failed to copy link");
    }
  };

  const ownerInitial = ownerName ? ownerName.charAt(0).toUpperCase() : "O";

  return (
    <>
      <div className="fixed inset-0 bg-black/70 z-40" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="bg-surface border border-line rounded-2xl shadow-2xl shadow-black/40 w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-line">
            <h2 className="text-lg font-semibold text-slate-100">
              Share &ldquo;{fileName}&rdquo;
            </h2>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-surface-hover text-slate-500 hover:text-slate-200 transition"
            >
              <X size={18} />
            </button>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-line">
            <button
              onClick={() => setActiveTab("people")}
              className={cn(
                "flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm font-medium transition",
                activeTab === "people"
                  ? "text-otter-300 border-b-2 border-otter-300"
                  : "text-slate-400 hover:text-slate-200"
              )}
            >
              <UserPlus size={16} />
              People
            </button>
            <button
              onClick={() => setActiveTab("link")}
              className={cn(
                "flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm font-medium transition",
                activeTab === "link"
                  ? "text-otter-300 border-b-2 border-otter-300"
                  : "text-slate-400 hover:text-slate-200"
              )}
            >
              <Globe size={16} />
              Get link
            </button>
          </div>

          {/* Content */}
          <div className="px-6 py-5">
            {activeTab === "people" ? (
              <div className="space-y-4">
                {shareError && (
                  <div
                    role="alert"
                    className="flex items-start gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-sm text-red-300"
                  >
                    <AlertCircle size={16} className="mt-0.5 flex-shrink-0 text-red-400" />
                    <span className="break-words min-w-0">{shareError}</span>
                  </div>
                )}
                {/* Email input + permission */}
                <div className="flex gap-2">
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="Add people by email"
                    className="flex-1 px-3.5 py-2.5 bg-surface-raised border border-line rounded-lg text-sm text-slate-100 placeholder-slate-500 hover:border-line-strong focus:outline-none focus:ring-2 focus:ring-otter-400 focus:border-transparent transition"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleShare();
                    }}
                  />
                  <select
                    value={permission}
                    onChange={(e) => setPermission(e.target.value as "view" | "edit")}
                    className="px-3 py-2.5 border border-line rounded-lg text-sm bg-surface-raised text-slate-300 hover:border-line-strong focus:outline-none focus:ring-2 focus:ring-otter-400"
                  >
                    <option value="view">Viewer</option>
                    <option value="edit">Editor</option>
                  </select>
                  <button
                    onClick={handleShare}
                    disabled={!email.trim() || isSharing}
                    className="px-4 py-2.5 bg-otter-500 text-white rounded-lg text-sm font-medium hover:bg-otter-400 transition disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isSharing ? "Sharing..." : "Share"}
                  </button>
                </div>

                {/* People with access list */}
                <div className="space-y-1">
                  <p className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                    People with access
                  </p>

                  {/* Owner row */}
                  {ownerId && (
                    <div className="flex items-center justify-between py-2">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-otter-500 flex items-center justify-center text-xs font-medium text-white">
                          {ownerInitial}
                        </div>
                        <div>
                          <p className="text-sm font-medium text-slate-100">
                            {ownerName || "Owner"}
                          </p>
                          {ownerEmail && (
                            <p className="text-xs text-slate-400">{ownerEmail}</p>
                          )}
                        </div>
                      </div>
                      <span className="text-xs text-slate-400 px-2 py-1 bg-surface-raised rounded-full">
                        Owner
                      </span>
                    </div>
                  )}

                  {/* Shared users */}
                  {sharedWith.length > 0 ? (
                    sharedWith
                      .filter((user) => user.userId !== ownerId)
                      .map((user) => {
                        const resolved = resolvedUsers[user.userId];
                        const displayName = resolved?.name || user.name || user.userId.slice(0, 8);
                        const displayEmail = resolved?.email || user.email;
                        const isUpdating = updatingUserId === user.userId;
                        const isRemoving = removingUserId === user.userId;
                        return (
                          <div
                            key={user.userId}
                            className="flex items-center justify-between py-2 group"
                          >
                            <div className="flex items-center gap-3 min-w-0">
                              <div className="w-8 h-8 rounded-full bg-otter-500/15 flex items-center justify-center text-xs font-medium text-otter-200 flex-shrink-0">
                                {displayName.charAt(0).toUpperCase()}
                              </div>
                              <div className="min-w-0">
                                <p className="text-sm font-medium text-slate-100 truncate">
                                  {displayName}
                                </p>
                                {displayEmail && (
                                  <p className="text-xs text-slate-400 truncate">{displayEmail}</p>
                                )}
                              </div>
                            </div>
                            <div className="flex items-center gap-1.5 flex-shrink-0">
                              <div className="relative">
                                <select
                                  value={user.permission === "edit" ? "edit" : "view"}
                                  onChange={(e) =>
                                    handlePermissionChange(
                                      user.userId,
                                      e.target.value as "view" | "edit"
                                    )
                                  }
                                  disabled={isUpdating || isRemoving}
                                  className={cn(
                                    "appearance-none pl-2 pr-6 py-1 text-xs rounded-full border cursor-pointer focus:outline-none focus:ring-2 focus:ring-otter-400 bg-surface-raised",
                                    isUpdating
                                      ? "opacity-50 cursor-wait"
                                      : "border-line text-slate-300 hover:border-line-strong"
                                  )}
                                >
                                  <option value="view">Viewer</option>
                                  <option value="edit">Editor</option>
                                </select>
                                <ChevronDown
                                  size={12}
                                  className="absolute right-1.5 top-1/2 -translate-y-1/2 text-slate-500 pointer-events-none"
                                />
                              </div>
                              <button
                                onClick={() => handleRemoveAccess(user.userId)}
                                disabled={isRemoving || isUpdating}
                                className={cn(
                                  "p-1 rounded-md transition",
                                  isRemoving
                                    ? "opacity-50 cursor-wait"
                                    : "text-slate-500 hover:text-red-400 hover:bg-red-500/10"
                                )}
                                title="Remove access"
                              >
                                <X size={14} />
                              </button>
                            </div>
                          </div>
                        );
                      })
                  ) : !ownerId ? (
                    <p className="text-sm text-slate-400 text-center py-4">
                      No one else has access yet
                    </p>
                  ) : null}

                  {ownerId && sharedWith.filter((u) => u.userId !== ownerId).length === 0 && (
                    <p className="text-sm text-slate-400 text-center py-3">
                      No one else has access yet
                    </p>
                  )}
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Link access mode toggle */}
                <div className="space-y-3">
                  <p className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                    General access
                  </p>
                  <button
                    onClick={() => {
                      setLinkAccess("restricted");
                    }}
                    className={cn(
                      "w-full flex items-center gap-3 p-3 rounded-xl border transition text-left",
                      linkAccess === "restricted"
                        ? "border-otter-500/40 bg-otter-500/15"
                        : "border-line hover:border-line-strong"
                    )}
                  >
                    <Lock
                      size={18}
                      className={cn(
                        linkAccess === "restricted" ? "text-otter-300" : "text-slate-500"
                      )}
                    />
                    <div className="flex-1">
                      <p
                        className={cn(
                          "text-sm font-medium",
                          linkAccess === "restricted" ? "text-otter-300" : "text-slate-300"
                        )}
                      >
                        Restricted
                      </p>
                      <p className="text-xs text-slate-400">
                        Only people explicitly shared with can access
                      </p>
                    </div>
                    {linkAccess === "restricted" && (
                      <Check size={16} className="text-otter-300 flex-shrink-0" />
                    )}
                  </button>
                  <button
                    onClick={() => {
                      setLinkAccess("anyone");
                    }}
                    className={cn(
                      "w-full flex items-center gap-3 p-3 rounded-xl border transition text-left",
                      linkAccess === "anyone"
                        ? "border-otter-500/40 bg-otter-500/15"
                        : "border-line hover:border-line-strong"
                    )}
                  >
                    <Globe
                      size={18}
                      className={cn(
                        linkAccess === "anyone" ? "text-otter-300" : "text-slate-500"
                      )}
                    />
                    <div className="flex-1">
                      <p
                        className={cn(
                          "text-sm font-medium",
                          linkAccess === "anyone" ? "text-otter-300" : "text-slate-300"
                        )}
                      >
                        Anyone with the link
                      </p>
                      <p className="text-xs text-slate-400">
                        Anyone with the link can view this file
                      </p>
                    </div>
                    {linkAccess === "anyone" && (
                      <Check size={16} className="text-otter-300 flex-shrink-0" />
                    )}
                  </button>
                </div>

                {/* Copy link section */}
                <div className="flex items-center gap-3 p-4 bg-surface-raised rounded-xl">
                  <Link2 size={20} className="text-slate-500 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-slate-300 truncate">
                      {typeof window !== "undefined"
                        ? `${window.location.origin}/files/${fileId}`
                        : `/files/${fileId}`}
                    </p>
                    <p className="text-xs text-slate-400 mt-0.5">
                      {linkAccess === "anyone"
                        ? "Anyone with the link can view this file"
                        : "Only people with access can open this link"}
                    </p>
                  </div>
                  <button
                    onClick={handleCopyLink}
                    className="flex items-center gap-1.5 px-3 py-2 bg-surface-raised border border-line rounded-lg text-sm font-medium text-slate-300 hover:bg-surface-hover hover:border-line-strong transition flex-shrink-0"
                  >
                    {copied ? (
                      <>
                        <Check size={14} className="text-green-400" />
                        Copied
                      </>
                    ) : (
                      <>
                        <Copy size={14} />
                        Copy link
                      </>
                    )}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
