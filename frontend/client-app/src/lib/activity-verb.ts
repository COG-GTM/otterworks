import type { AuditEvent } from "./api";

const PERMISSION_LABELS: Record<string, string> = {
  editor: "edit",
  edit: "edit",
  viewer: "view",
  view: "view",
};

/**
 * Human-readable phrase for an audit event, e.g. "shared with Priya (edit)",
 * "renamed from Q3.xlsx", "moved to Finance/2026", "downloaded".
 * `resolveUserName` maps a user id to a display name when one is known.
 */
export function formatActivityVerb(
  event: AuditEvent,
  resolveUserName: (userId: string) => string | undefined = () => undefined
): string {
  const details = event.details ?? {};
  const permission = details.permission ? PERMISSION_LABELS[details.permission] ?? details.permission : undefined;

  switch (event.action) {
    case "upload":
      return details.name ? `uploaded ${details.name}` : "uploaded this file";
    case "rename":
      return details.previousName ? `renamed from ${details.previousName}` : "renamed this file";
    case "update":
      return "updated this file";
    case "move":
      return details.folderName ? `moved to ${details.folderName}` : "moved this file";
    case "share": {
      const target = details.sharedWithUserId
        ? resolveUserName(details.sharedWithUserId) ?? shortId(details.sharedWithUserId)
        : "someone";
      return permission ? `shared with ${target} (${permission})` : `shared with ${target}`;
    }
    case "unshare": {
      const target = details.sharedWithUserId
        ? resolveUserName(details.sharedWithUserId) ?? shortId(details.sharedWithUserId)
        : "someone";
      return `removed access for ${target}`;
    }
    case "download":
      return "downloaded";
    case "trash":
      return "moved to trash";
    case "restore":
      return "restored from trash";
    case "delete":
      return "deleted this file";
    case "create":
      return "created this file";
    default:
      return event.action.replace(/_/g, " ");
  }
}

function shortId(userId: string): string {
  return userId.slice(0, 8);
}
