import { http, HttpResponse } from "msw";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FolderShareDialog } from "./folder-share-dialog";
import { billingServer as server } from "../../test-setup";
import { API, renderWithProviders } from "../../test/render";
import { formatExpiresAt } from "@/lib/share-links";

const FOLDER_ID = "f-1";
const DAY = 86400;

const policy = (overrides: Record<string, unknown> = {}) => ({
  workspace_id: "default",
  default_expiry_seconds: 30 * DAY,
  min_expiry_seconds: 3600,
  max_expiry_seconds: 90 * DAY,
  allow_never: false,
  updated_by: null,
  updated_at: null,
  ...overrides,
});

const link = (id: string, status: string, overrides: Record<string, unknown> = {}) => ({
  id,
  folder_id: FOLDER_ID,
  created_by: "u-1",
  created_at: "2026-11-01T10:00:00Z",
  expires_at: "2026-12-01T10:00:00Z",
  revoked_at: status === "revoked" ? "2026-11-05T10:00:00Z" : null,
  status,
  ...overrides,
});

function mockApi({
  policyBody = policy(),
  links = [] as ReturnType<typeof link>[],
}: { policyBody?: ReturnType<typeof policy>; links?: ReturnType<typeof link>[] } = {}) {
  const calls: { method: string; path: string; body?: unknown }[] = [];
  server.use(
    http.get(`${API}/documents/share-policy`, () => HttpResponse.json(policyBody)),
    http.get(`${API}/documents/folders/${FOLDER_ID}/share-links`, () => HttpResponse.json({ items: links })),
    http.post(`${API}/documents/folders/${FOLDER_ID}/share-links`, async ({ request }) => {
      const body = await request.json();
      calls.push({ method: "POST", path: "create", body });
      return HttpResponse.json(
        {
          ...link("new-1", "active", { expires_at: "2026-12-10T10:00:00Z" }),
          token: "tok_abc",
          url: "https://otter.example/shared-folder/tok_abc",
        },
        { status: 201 }
      );
    }),
    http.patch(`${API}/documents/share-links/:id`, async ({ request, params }) => {
      const body = await request.json();
      calls.push({ method: "PATCH", path: String(params.id), body });
      return HttpResponse.json(link(String(params.id), "active"));
    }),
    http.delete(`${API}/documents/share-links/:id`, ({ params }) => {
      calls.push({ method: "DELETE", path: String(params.id) });
      return new HttpResponse(null, { status: 204 });
    })
  );
  return calls;
}

function renderDialog() {
  return renderWithProviders(
    <FolderShareDialog folderId={FOLDER_ID} folderName="Q4 Plans" onClose={() => {}} />
  );
}

async function expirySelect() {
  const select = await screen.findByLabelText<HTMLSelectElement>("Link expires after");
  await waitFor(() => expect(select).not.toBeDisabled());
  return select;
}

describe("FolderShareDialog — create link", () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  beforeEach(() => {
    writeText.mockClear();
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  });

  it("preselects the workspace default and offers only allowed expiry values (no Never)", async () => {
    mockApi();
    renderDialog();
    const select = await expirySelect();
    expect(select.value).toBe(String(30 * DAY));
    const labels = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(labels).toEqual(["1 hour", "1 day", "7 days", "30 days (default)", "90 days"]);
  });

  it("offers Never when the workspace allows it", async () => {
    mockApi({ policyBody: policy({ allow_never: true }) });
    renderDialog();
    const select = await expirySelect();
    expect(within(select).getByRole("option", { name: "Never" })).toBeInTheDocument();
  });

  it("creates a link with the chosen expiry, shows the URL and expires_at, and copies it", async () => {
    const calls = mockApi();
    renderDialog();
    const select = await expirySelect();
    fireEvent.change(select, { target: { value: String(7 * DAY) } });
    fireEvent.click(screen.getByRole("button", { name: /create link/i }));

    const url = await screen.findByLabelText<HTMLInputElement>("Share link URL");
    expect(url.value).toBe("https://otter.example/shared-folder/tok_abc");
    expect(calls).toContainEqual({ method: "POST", path: "create", body: { expires_in_seconds: 7 * DAY } });
    expect(screen.getByTestId("created-link")).toHaveTextContent(formatExpiresAt("2026-12-10T10:00:00Z"));

    fireEvent.click(screen.getByRole("button", { name: /copy link/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("https://otter.example/shared-folder/tok_abc"));
  });

  it("sends never: true when Never is chosen", async () => {
    const calls = mockApi({ policyBody: policy({ allow_never: true }) });
    renderDialog();
    fireEvent.change(await expirySelect(), { target: { value: "never" } });
    fireEvent.click(screen.getByRole("button", { name: /create link/i }));
    await screen.findByLabelText("Share link URL");
    expect(calls).toContainEqual({ method: "POST", path: "create", body: { never: true } });
  });

  it("shows the allowed range when the API rejects the expiry (422)", async () => {
    mockApi();
    server.use(
      http.post(`${API}/documents/folders/${FOLDER_ID}/share-links`, () =>
        HttpResponse.json(
          { detail: "expiry out of range", min_expiry_seconds: 3600, max_expiry_seconds: 90 * DAY, allow_never: false },
          { status: 422 }
        )
      )
    );
    renderDialog();
    await expirySelect();
    fireEvent.click(screen.getByRole("button", { name: /create link/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose an expiry between 1 hour and 90 days.");
  });

  it("explains a 403 for a folder the user does not own", async () => {
    mockApi();
    server.use(
      http.post(`${API}/documents/folders/${FOLDER_ID}/share-links`, () =>
        HttpResponse.json({ detail: "Forbidden" }, { status: 403 })
      )
    );
    renderDialog();
    await expirySelect();
    fireEvent.click(screen.getByRole("button", { name: /create link/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Only the folder owner can manage share links.");
  });
});

describe("FolderShareDialog — existing links", () => {
  const links = [
    link("l-active", "active"),
    link("l-expired", "expired", { expires_at: "2026-11-02T10:00:00Z" }),
    link("l-revoked", "revoked"),
  ];

  it("shows status for each link and only lets active links be changed or revoked", async () => {
    mockApi({ links });
    renderDialog();
    const active = await screen.findByTestId("share-link-l-active");
    const expired = screen.getByTestId("share-link-l-expired");
    const revoked = screen.getByTestId("share-link-l-revoked");

    expect(within(active).getByText("Active")).toBeInTheDocument();
    expect(within(expired).getByText("Expired")).toBeInTheDocument();
    expect(within(revoked).getByText("Revoked")).toBeInTheDocument();
    expect(active).toHaveTextContent(formatExpiresAt("2026-12-01T10:00:00Z"));

    expect(within(active).getByRole("button", { name: "Revoke" })).toBeInTheDocument();
    expect(within(active).getByLabelText("Change expiry")).toBeInTheDocument();
    for (const row of [expired, revoked]) {
      expect(within(row).queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument();
      expect(within(row).queryByLabelText("Change expiry")).not.toBeInTheDocument();
    }
  });

  it("changes expiry within policy (only allowed values offered)", async () => {
    const calls = mockApi({ links });
    renderDialog();
    const active = await screen.findByTestId("share-link-l-active");
    await expirySelect();
    const change = within(active).getByLabelText<HTMLSelectElement>("Change expiry");
    const values = within(change).getAllByRole("option").map((o) => (o as HTMLOptionElement).value);
    expect(values).toEqual(["", "3600", "86400", String(7 * DAY), String(30 * DAY), String(90 * DAY)]);

    fireEvent.change(change, { target: { value: String(7 * DAY) } });
    await waitFor(() =>
      expect(calls).toContainEqual({ method: "PATCH", path: "l-active", body: { expires_in_seconds: 7 * DAY } })
    );
  });

  it("shows a message when the link already expired (409)", async () => {
    mockApi({ links });
    server.use(
      http.patch(`${API}/documents/share-links/:id`, () =>
        HttpResponse.json({ detail: "Share link expired" }, { status: 409 })
      )
    );
    renderDialog();
    const active = await screen.findByTestId("share-link-l-active");
    await expirySelect();
    fireEvent.change(within(active).getByLabelText("Change expiry"), { target: { value: "86400" } });
    expect(await screen.findByRole("alert")).toHaveTextContent(/already expired or been revoked/);
  });

  it("revokes a link after confirmation", async () => {
    const calls = mockApi({ links });
    renderDialog();
    const active = await screen.findByTestId("share-link-l-active");
    fireEvent.click(within(active).getByRole("button", { name: "Revoke" }));
    const confirm = await screen.findByRole("dialog", { name: "Revoke this link?" });
    fireEvent.click(within(confirm).getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(calls).toContainEqual({ method: "DELETE", path: "l-active" }));
  });
});
