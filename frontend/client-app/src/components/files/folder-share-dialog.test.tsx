import { http, HttpResponse } from "msw";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FolderShareDialog } from "./folder-share-dialog";
import { billingServer as server } from "../../test-setup";

const API = "http://localhost:3000/api/v1";
const FOLDER_ID = "11111111-1111-1111-1111-111111111111";
const POLICY_URL = `${API}/admin/sharing_policy`;
const LINKS_URL = `${API}/folder-share-links`;

type RawLink = {
  id: string;
  folder_id: string;
  created_by: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
  status: "active" | "expired" | "revoked";
};

function link(id: string, status: RawLink["status"], overrides: Partial<RawLink> = {}): RawLink {
  return {
    id,
    folder_id: FOLDER_ID,
    created_by: "owner-1",
    created_at: "2026-11-01T10:00:00Z",
    expires_at: "2026-12-01T10:00:00Z",
    revoked_at: status === "revoked" ? "2026-11-05T10:00:00Z" : null,
    status,
    ...overrides,
  };
}

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <FolderShareDialog folderId={FOLDER_ID} folderName="Q4 Reports" onClose={onClose} />
    </QueryClientProvider>
  );
  return { onClose };
}

function usePolicy(policy: { default_expiry_days: number; min_expiry_days: number; max_expiry_days: number }) {
  server.use(http.get(POLICY_URL, () => HttpResponse.json(policy)));
}

function useLinks(links: RawLink[]) {
  server.use(http.get(LINKS_URL, () => HttpResponse.json(links)));
}

const expiryInput = () => screen.getByLabelText("Expires after (days)") as HTMLInputElement;
const createButton = () => screen.getByRole("button", { name: /create link/i });

describe("FolderShareDialog", () => {
  const writeText = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    writeText.mockClear();
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  });

  // US1: Given I own folder F, When I create a share link without picking an expiry,
  // Then expires_at = created_at + workspace default, and the raw token is returned once.
  it("US1 create without picking an expiry: shows the policy default, sends no override, and lets me copy the link", async () => {
    usePolicy({ default_expiry_days: 14, min_expiry_days: 1, max_expiry_days: 60 });
    useLinks([]);
    let body: Record<string, unknown> | null = null;
    server.use(
      http.post(LINKS_URL, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            id: "link-1",
            folder_id: FOLDER_ID,
            token: "raw-token-abc",
            created_at: "2026-11-10T10:00:00Z",
            expires_at: "2026-11-24T10:00:00Z",
          },
          { status: 201 }
        );
      })
    );
    renderDialog();

    await waitFor(() => expect(expiryInput().value).toBe("14"));
    expect(screen.getByText("Workspace default: 14 days. Allowed: 1 to 60 days.")).toBeInTheDocument();

    fireEvent.click(createButton());

    const url = await screen.findByLabelText("Share link URL");
    expect(body).toEqual({ folder_id: FOLDER_ID });
    expect((url as HTMLInputElement).value).toBe("http://localhost:3000/shared/folders/raw-token-abc");
    expect(screen.getByText(/the full link is only shown once/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /copy link/i }));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith("http://localhost:3000/shared/folders/raw-token-abc")
    );
    expect(await screen.findByRole("button", { name: /copied/i })).toBeInTheDocument();
  });

  // US1: Given I do not own folder F, When I try to create a share link, Then it is rejected with 403.
  it("US1 non-owner: a 403 from create shows an owner-only message and no link", async () => {
    usePolicy({ default_expiry_days: 30, min_expiry_days: 1, max_expiry_days: 90 });
    useLinks([]);
    server.use(http.post(LINKS_URL, () => HttpResponse.json({ detail: "forbidden" }, { status: 403 })));
    renderDialog();

    await waitFor(() => expect(createButton()).toBeEnabled());
    fireEvent.click(createButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only the folder owner can manage share links."
    );
    expect(screen.queryByLabelText("Share link URL")).not.toBeInTheDocument();
  });

  // US2: Given no policy has been configured (or it cannot be read), Then default 30, min 1, max 90.
  it("US2 no policy available: falls back to 30 days default within 1 to 90", async () => {
    server.use(http.get(POLICY_URL, () => HttpResponse.json({ error: "down" }, { status: 503 })));
    useLinks([]);
    renderDialog();

    await waitFor(() => expect(expiryInput()).toBeEnabled());
    expect(expiryInput().value).toBe("30");
    expect(expiryInput()).toHaveAttribute("min", "1");
    expect(expiryInput()).toHaveAttribute("max", "90");
    expect(screen.getByText("Workspace default: 30 days. Allowed: 1 to 90 days.")).toBeInTheDocument();
  });

  // US3: Given I create a link, When I choose an expiry inside the bounds, Then expires_at uses that value.
  it("US3 override inside bounds: sends expires_in_days", async () => {
    usePolicy({ default_expiry_days: 30, min_expiry_days: 1, max_expiry_days: 90 });
    useLinks([]);
    let body: Record<string, unknown> | null = null;
    server.use(
      http.post(LINKS_URL, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            id: "link-2",
            folder_id: FOLDER_ID,
            token: "tok-2",
            created_at: "2026-11-10T10:00:00Z",
            expires_at: "2026-11-17T10:00:00Z",
          },
          { status: 201 }
        );
      })
    );
    renderDialog();

    await waitFor(() => expect(expiryInput()).toBeEnabled());
    fireEvent.change(expiryInput(), { target: { value: "7" } });
    fireEvent.click(createButton());

    await screen.findByLabelText("Share link URL");
    expect(body).toEqual({ folder_id: FOLDER_ID, expires_in_days: 7 });
  });

  // US3: Given I choose a value outside the bounds, or "never", Then it is rejected with a message
  // stating the allowed range.
  it.each([["0"], ["91"], ["2.5"], [""]])(
    "US3 out of bounds (%s): shows the allowed range and blocks create",
    async (value) => {
      usePolicy({ default_expiry_days: 30, min_expiry_days: 1, max_expiry_days: 90 });
      useLinks([]);
      renderDialog();

      await waitFor(() => expect(expiryInput()).toBeEnabled());
      fireEvent.change(expiryInput(), { target: { value } });

      expect(screen.getByText("Choose an expiry between 1 and 90 days.")).toBeInTheDocument();
      expect(expiryInput()).toHaveAttribute("aria-invalid", "true");
      expect(createButton()).toBeDisabled();
    }
  );

  it("US3 no \"never\" option: the picker is a bounded number of days only", async () => {
    usePolicy({ default_expiry_days: 30, min_expiry_days: 1, max_expiry_days: 90 });
    useLinks([]);
    renderDialog();

    await waitFor(() => expect(expiryInput()).toBeEnabled());
    expect(expiryInput()).toHaveAttribute("type", "number");
    expect(screen.queryByText(/never/i)).not.toBeInTheDocument();
  });

  it("US3 server rejects with 422: shows the allowed range", async () => {
    usePolicy({ default_expiry_days: 30, min_expiry_days: 1, max_expiry_days: 90 });
    useLinks([]);
    server.use(
      http.post(LINKS_URL, () => HttpResponse.json({ detail: "out of range" }, { status: 422 }))
    );
    renderDialog();

    await waitFor(() => expect(createButton()).toBeEnabled());
    fireEvent.click(createButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Choose an expiry between 1 and 90 days."
    );
  });

  // Dialog lists existing links with status and never shows their tokens.
  it("lists existing links with active, expired and revoked status; only active links can be revoked", async () => {
    usePolicy({ default_expiry_days: 30, min_expiry_days: 1, max_expiry_days: 90 });
    useLinks([link("a", "active"), link("e", "expired"), link("r", "revoked")]);
    renderDialog();

    const rows = await screen.findAllByTestId("folder-share-link-row");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByText("Active")).toBeInTheDocument();
    expect(within(rows[0]).getByRole("button", { name: "Revoke" })).toBeInTheDocument();
    expect(within(rows[1]).getByText("Expired")).toBeInTheDocument();
    expect(within(rows[1]).queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument();
    expect(within(rows[2]).getByText("Revoked")).toBeInTheDocument();
    expect(within(rows[2]).queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Share link URL")).not.toBeInTheDocument();
  });

  // US3: Given I revoke a link, Then it stops working at once and its record is kept.
  it("US3 revoke: calls DELETE and the link stays listed as revoked", async () => {
    usePolicy({ default_expiry_days: 30, min_expiry_days: 1, max_expiry_days: 90 });
    let revoked = false;
    let deletedId: string | null = null;
    server.use(
      http.get(LINKS_URL, () => HttpResponse.json([link("a", revoked ? "revoked" : "active")])),
      http.delete(`${LINKS_URL}/:id`, ({ params }) => {
        deletedId = params.id as string;
        revoked = true;
        return new HttpResponse(null, { status: 204 });
      })
    );
    renderDialog();

    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));

    await waitFor(() => expect(screen.getByText("Revoked")).toBeInTheDocument());
    expect(deletedId).toBe("a");
    expect(screen.getAllByTestId("folder-share-link-row")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument();
  });

  it("closes from the header button", async () => {
    usePolicy({ default_expiry_days: 30, min_expiry_days: 1, max_expiry_days: 90 });
    useLinks([]);
    const { onClose } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalled();
  });
});
