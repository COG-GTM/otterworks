import { useState, type ReactNode } from "react";
import { X, Link2, Copy, Check, UserPlus, Globe, Lock, ChevronDown, AlertCircle, type LucideIcon } from "lucide-react";
import { isAxiosError } from "axios";
import toast from "react-hot-toast";
import { cn } from "@/lib/utils";
import { filesApi } from "@/lib/api";
import type { SharedUser } from "@/types";

type Permission = "view" | "edit";
type LinkAccess = "restricted" | "anyone";
type Tab = "people" | "link";
type ResolvedUsers = Record<string, { name: string; email: string }>;

interface ShareDialogProps {
  fileId: string;
  fileName: string;
  ownerId?: string;
  ownerName?: string;
  ownerEmail?: string;
  sharedWith: SharedUser[];
  resolvedUsers?: ResolvedUsers;
  onShare: (email: string, permission: Permission) => Promise<void>;
  onClose: () => void;
  onPermissionChange?: (userId: string, permission: Permission) => Promise<void>;
  onRemoveAccess?: (userId: string) => Promise<void>;
}

const AWS_ERROR_CODES = new Set(["event_error", "storage_error"]);

function shareErrorMessage(err: unknown): string {
  if (!isAxiosError(err)) return "Sharing failed.";
  const data = err.response?.data as { error?: string; message?: string } | undefined;
  const detail = data?.message;
  if (!detail) return "Sharing failed.";
  return AWS_ERROR_CODES.has(data?.error ?? "") ? `Sharing failed. AWS ${detail}` : `Sharing failed: ${detail}`;
}

function fileShareUrl(fileId: string): string {
  return typeof window === "undefined" ? `/files/${fileId}` : `${window.location.origin}/files/${fileId}`;
}

function useShareForm(onShare: (email: string, permission: Permission) => Promise<void>) {
  const [email, setEmail] = useState("");
  const [permission, setPermission] = useState<Permission>("view");
  const [isSharing, setIsSharing] = useState(false);
  const [shareError, setShareError] = useState<string | null>(null);

  const handleShare = async () => {
    const target = email.trim();
    if (!target) return;
    setIsSharing(true);
    setShareError(null);
    try {
      await onShare(target, permission);
      setEmail("");
      toast.success(`Shared with ${target}`);
    } catch (err) {
      const message = shareErrorMessage(err);
      setShareError(message);
      toast.error(message);
    } finally {
      setIsSharing(false);
    }
  };

  return { email, setEmail, permission, setPermission, isSharing, shareError, handleShare };
}

function useAccessActions(
  changePermission: (userId: string, permission: Permission) => Promise<unknown>,
  removeAccess: (userId: string) => Promise<unknown>
) {
  const [updatingUserId, setUpdatingUserId] = useState<string | null>(null);
  const [removingUserId, setRemovingUserId] = useState<string | null>(null);

  const handlePermissionChange = async (userId: string, newPermission: Permission) => {
    setUpdatingUserId(userId);
    try {
      await changePermission(userId, newPermission);
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
      await removeAccess(userId);
      toast.success("Access removed");
    } catch {
      toast.error("Failed to remove access");
    } finally {
      setRemovingUserId(null);
    }
  };

  return { updatingUserId, removingUserId, handlePermissionChange, handleRemoveAccess };
}

function useLinkSharing(shareUrl: string) {
  const [linkAccess, setLinkAccess] = useState<LinkAccess>("restricted");
  const [copied, setCopied] = useState(false);

  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      toast.success("Link copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Failed to copy link");
    }
  };

  return { shareUrl, linkAccess, setLinkAccess, copied, handleCopyLink };
}

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
  const [activeTab, setActiveTab] = useState<Tab>("people");
  const shareForm = useShareForm(onShare);
  const access = useAccessActions(
    (userId, permission) =>
      onPermissionChange
        ? onPermissionChange(userId, permission)
        : filesApi.updateSharePermission(fileId, userId, permission),
    (userId) => (onRemoveAccess ? onRemoveAccess(userId) : filesApi.removeShare(fileId, userId))
  );
  const link = useLinkSharing(fileShareUrl(fileId));

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900">
              Share &ldquo;{fileName}&rdquo;
            </h2>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition"
            >
              <X size={18} />
            </button>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-gray-200">
            <TabButton icon={UserPlus} active={activeTab === "people"} onClick={() => setActiveTab("people")}>
              People
            </TabButton>
            <TabButton icon={Globe} active={activeTab === "link"} onClick={() => setActiveTab("link")}>
              Get link
            </TabButton>
          </div>

          {/* Content */}
          <div className="px-6 py-5">
            {activeTab === "people" ? (
              <PeoplePanel
                ownerId={ownerId}
                ownerName={ownerName}
                ownerEmail={ownerEmail}
                sharedWith={sharedWith}
                resolvedUsers={resolvedUsers}
                shareForm={shareForm}
                access={access}
              />
            ) : (
              <LinkPanel link={link} />
            )}
          </div>
        </div>
      </div>
    </>
  );
}

function TabButton({
  icon: Icon,
  active,
  onClick,
  children,
}: {
  icon: LucideIcon;
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm font-medium transition",
        active ? "text-otter-600 border-b-2 border-otter-600" : "text-gray-500 hover:text-gray-700"
      )}
    >
      <Icon size={16} />
      {children}
    </button>
  );
}

interface PeoplePanelProps {
  ownerId?: string;
  ownerName?: string;
  ownerEmail?: string;
  sharedWith: SharedUser[];
  resolvedUsers: ResolvedUsers;
  shareForm: ReturnType<typeof useShareForm>;
  access: ReturnType<typeof useAccessActions>;
}

function PeoplePanel({ ownerId, ownerName, ownerEmail, sharedWith, resolvedUsers, shareForm, access }: PeoplePanelProps) {
  const others = sharedWith.filter((user) => user.userId !== ownerId);

  return (
    <div className="space-y-4">
      <ShareForm form={shareForm} />

      {/* People with access list */}
      <div className="space-y-1">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">
          People with access
        </p>

        {ownerId && <OwnerRow name={ownerName} email={ownerEmail} />}

        {others.map((user) => (
          <SharedUserRow
            key={user.userId}
            user={user}
            resolved={resolvedUsers[user.userId]}
            isUpdating={access.updatingUserId === user.userId}
            isRemoving={access.removingUserId === user.userId}
            onPermissionChange={access.handlePermissionChange}
            onRemoveAccess={access.handleRemoveAccess}
          />
        ))}

        {others.length === 0 && (
          <p className={cn("text-sm text-gray-500 text-center", ownerId ? "py-3" : "py-4")}>
            No one else has access yet
          </p>
        )}
      </div>
    </div>
  );
}

function ShareForm({ form }: { form: ReturnType<typeof useShareForm> }) {
  const { email, setEmail, permission, setPermission, isSharing, shareError, handleShare } = form;

  return (
    <>
      {shareError && (
        <div
          role="alert"
          className="flex items-start gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700"
        >
          <AlertCircle size={16} className="mt-0.5 flex-shrink-0 text-red-500" />
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
          className="flex-1 px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-otter-500 focus:border-transparent transition"
          onKeyDown={(e) => {
            if (e.key === "Enter") handleShare();
          }}
        />
        <select
          value={permission}
          onChange={(e) => setPermission(e.target.value as Permission)}
          className="px-3 py-2.5 border border-gray-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-otter-500"
        >
          <option value="view">Viewer</option>
          <option value="edit">Editor</option>
        </select>
        <button
          onClick={handleShare}
          disabled={!email.trim() || isSharing}
          className="px-4 py-2.5 bg-otter-600 text-white rounded-lg text-sm font-medium hover:bg-otter-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isSharing ? "Sharing..." : "Share"}
        </button>
      </div>
    </>
  );
}

function OwnerRow({ name, email }: { name?: string; email?: string }) {
  return (
    <div className="flex items-center justify-between py-2">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-full bg-otter-600 flex items-center justify-center text-xs font-medium text-white">
          {name ? name.charAt(0).toUpperCase() : "O"}
        </div>
        <div>
          <p className="text-sm font-medium text-gray-900">{name || "Owner"}</p>
          {email && <p className="text-xs text-gray-500">{email}</p>}
        </div>
      </div>
      <span className="text-xs text-gray-500 px-2 py-1 bg-gray-100 rounded-full">Owner</span>
    </div>
  );
}

interface SharedUserRowProps {
  user: SharedUser;
  resolved?: { name: string; email: string };
  isUpdating: boolean;
  isRemoving: boolean;
  onPermissionChange: (userId: string, permission: Permission) => void;
  onRemoveAccess: (userId: string) => void;
}

function SharedUserRow({
  user,
  resolved,
  isUpdating,
  isRemoving,
  onPermissionChange,
  onRemoveAccess,
}: SharedUserRowProps) {
  const displayName = resolved?.name || user.name || user.userId.slice(0, 8);
  const displayEmail = resolved?.email || user.email;
  const isBusy = isUpdating || isRemoving;

  return (
    <div className="flex items-center justify-between py-2 group">
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-8 h-8 rounded-full bg-otter-100 flex items-center justify-center text-xs font-medium text-otter-700 flex-shrink-0">
          {displayName.charAt(0).toUpperCase()}
        </div>
        <div className="min-w-0">
          <p className="text-sm font-medium text-gray-900 truncate">{displayName}</p>
          {displayEmail && <p className="text-xs text-gray-500 truncate">{displayEmail}</p>}
        </div>
      </div>
      <div className="flex items-center gap-1.5 flex-shrink-0">
        <div className="relative">
          <select
            value={user.permission === "edit" ? "edit" : "view"}
            onChange={(e) => onPermissionChange(user.userId, e.target.value as Permission)}
            disabled={isBusy}
            className={cn(
              "appearance-none pl-2 pr-6 py-1 text-xs rounded-full border cursor-pointer focus:outline-none focus:ring-2 focus:ring-otter-500 bg-white",
              isUpdating ? "opacity-50 cursor-wait" : "border-gray-200 text-gray-600 hover:border-gray-300"
            )}
          >
            <option value="view">Viewer</option>
            <option value="edit">Editor</option>
          </select>
          <ChevronDown
            size={12}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none"
          />
        </div>
        <button
          onClick={() => onRemoveAccess(user.userId)}
          disabled={isBusy}
          className={cn(
            "p-1 rounded-md transition",
            isRemoving ? "opacity-50 cursor-wait" : "text-gray-400 hover:text-red-500 hover:bg-red-50"
          )}
          title="Remove access"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}

function LinkPanel({ link }: { link: ReturnType<typeof useLinkSharing> }) {
  const { shareUrl, linkAccess, setLinkAccess, copied, handleCopyLink } = link;

  return (
    <div className="space-y-4">
      {/* Link access mode toggle */}
      <div className="space-y-3">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">General access</p>
        <LinkAccessOption
          icon={Lock}
          title="Restricted"
          description="Only people explicitly shared with can access"
          selected={linkAccess === "restricted"}
          onSelect={() => setLinkAccess("restricted")}
        />
        <LinkAccessOption
          icon={Globe}
          title="Anyone with the link"
          description="Anyone with the link can view this file"
          selected={linkAccess === "anyone"}
          onSelect={() => setLinkAccess("anyone")}
        />
      </div>

      {/* Copy link section */}
      <div className="flex items-center gap-3 p-4 bg-gray-50 rounded-xl">
        <Link2 size={20} className="text-gray-400 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-gray-700 truncate">{shareUrl}</p>
          <p className="text-xs text-gray-500 mt-0.5">
            {linkAccess === "anyone"
              ? "Anyone with the link can view this file"
              : "Only people with access can open this link"}
          </p>
        </div>
        <button
          onClick={handleCopyLink}
          className="flex items-center gap-1.5 px-3 py-2 bg-white border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 transition flex-shrink-0"
        >
          {copied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
          {copied ? "Copied" : "Copy link"}
        </button>
      </div>
    </div>
  );
}

interface LinkAccessOptionProps {
  icon: LucideIcon;
  title: string;
  description: string;
  selected: boolean;
  onSelect: () => void;
}

function LinkAccessOption({ icon: Icon, title, description, selected, onSelect }: LinkAccessOptionProps) {
  return (
    <button
      onClick={onSelect}
      className={cn(
        "w-full flex items-center gap-3 p-3 rounded-xl border transition text-left",
        selected ? "border-otter-300 bg-otter-50" : "border-gray-200 hover:border-gray-300"
      )}
    >
      <Icon size={18} className={cn(selected ? "text-otter-600" : "text-gray-400")} />
      <div className="flex-1">
        <p className={cn("text-sm font-medium", selected ? "text-otter-700" : "text-gray-700")}>{title}</p>
        <p className="text-xs text-gray-500">{description}</p>
      </div>
      {selected && <Check size={16} className="text-otter-600 flex-shrink-0" />}
    </button>
  );
}
