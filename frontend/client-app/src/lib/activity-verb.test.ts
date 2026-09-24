import { describe, it, expect } from "vitest";
import { formatActivityVerb } from "./activity-verb";
import type { AuditEvent } from "./api";

function event(action: string, details?: Record<string, string>): AuditEvent {
  return {
    id: "e1",
    userId: "user-a",
    action,
    resourceType: "file",
    resourceId: "file-1",
    details,
    timestamp: "2026-09-24T10:00:00Z",
  };
}

const names: Record<string, string> = { "user-b": "Priya" };
const resolve = (id: string) => names[id];

describe("formatActivityVerb", () => {
  it("describes a share with the recipient name and permission", () => {
    expect(
      formatActivityVerb(event("share", { sharedWithUserId: "user-b", permission: "editor" }), resolve)
    ).toBe("shared with Priya (edit)");
    expect(
      formatActivityVerb(event("share", { sharedWithUserId: "user-b", permission: "viewer" }), resolve)
    ).toBe("shared with Priya (view)");
  });

  it("falls back to a short id when the recipient is unknown", () => {
    expect(formatActivityVerb(event("share", { sharedWithUserId: "abcdefgh-1234" }))).toBe(
      "shared with abcdefgh"
    );
  });

  it("describes a rename with the previous name", () => {
    expect(formatActivityVerb(event("rename", { previousName: "Q3.xlsx", name: "Q4.xlsx" }))).toBe(
      "renamed from Q3.xlsx"
    );
  });

  it("describes a move with the destination folder", () => {
    expect(formatActivityVerb(event("move", { folderName: "Finance/2026" }))).toBe(
      "moved to Finance/2026"
    );
    expect(formatActivityVerb(event("move"))).toBe("moved this file");
  });

  it("describes uploads, downloads, unshares and trash transitions", () => {
    expect(formatActivityVerb(event("upload", { name: "Q3.xlsx" }))).toBe("uploaded Q3.xlsx");
    expect(formatActivityVerb(event("download"))).toBe("downloaded");
    expect(formatActivityVerb(event("unshare", { sharedWithUserId: "user-b" }), resolve)).toBe(
      "removed access for Priya"
    );
    expect(formatActivityVerb(event("trash"))).toBe("moved to trash");
    expect(formatActivityVerb(event("restore"))).toBe("restored from trash");
  });

  it("humanizes unknown actions", () => {
    expect(formatActivityVerb(event("custom_action"))).toBe("custom action");
  });
});
