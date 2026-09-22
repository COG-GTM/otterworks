import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ShareDialog } from "./share-dialog";
import type { SharedUser } from "@/types";

const pendingInvitee: SharedUser = {
  userId: "b3c1f0a8-0000-5000-8000-000000000000",
  name: "",
  email: "outside@example.com",
  permission: "view",
  status: "pending",
};

const member: SharedUser = {
  userId: "11111111-2222-3333-4444-555555555555",
  name: "Ada Otter",
  email: "ada@otterworks.io",
  permission: "edit",
  status: "active",
};

function renderDialog(sharedWith: SharedUser[]) {
  return render(
    <ShareDialog
      fileId="folder-1"
      fileName="Docs"
      ownerId="owner-1"
      sharedWith={sharedWith}
      onShare={vi.fn()}
      onClose={vi.fn()}
    />
  );
}

describe("ShareDialog", () => {
  it("lists a pending external invitee by email with a Pending badge", () => {
    renderDialog([pendingInvitee]);
    expect(screen.getAllByText("outside@example.com").length).toBeGreaterThan(0);
    expect(screen.getByText("Pending")).toBeInTheDocument();
  });

  it("does not mark existing members as pending", () => {
    renderDialog([member]);
    expect(screen.getByText("Ada Otter")).toBeInTheDocument();
    expect(screen.queryByText("Pending")).not.toBeInTheDocument();
  });
});
