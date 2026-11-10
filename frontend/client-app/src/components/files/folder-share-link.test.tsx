import { http, HttpResponse } from "msw";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { billingServer as server } from "../../test-setup";
import { ShareDialog } from "./share-dialog";
import { FolderCard } from "./folder-card";
import { expiryDayOptions, formatExpiry, shareLinkUrl } from "./folder-share-link-panel";
import type { FileItem } from "@/types";

const API = "http://localhost:3000/api/v1";
const FOLDER_ID = "6f1c2c3e-1111-4a4a-9b9b-000000000001";

const policy = (defaultDays: number, maxDays: number) =>
  http.get(`${API}/workspace/share-policy`, () =>
    HttpResponse.json({
      workspace_id: "default",
      default_days: defaultDays,
      max_days: maxDays,
      updated_at: null,
      updated_by: null,
    })
  );

const noLinks = http.get(`${API}/share-links`, () => HttpResponse.json([]));

const linkBody = (overrides: Record<string, unknown> = {}) => ({
  id: "link-1",
  token: "tok_abc123",
  url: "http://gateway/s/tok_abc123",
  resource_type: "folder",
  resource_id: FOLDER_ID,
  expires_at: "2026-12-10T12:00:00Z",
  created_at: "2026-11-10T12:00:00Z",
  ...overrides,
});

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ShareDialog resourceType="folder" fileId={FOLDER_ID} fileName="Q4 Reports" onClose={() => {}} />
    </QueryClientProvider>
  );
}

const picker = () => screen.findByRole("combobox");
const optionValues = (select: HTMLElement) =>
  within(select)
    .getAllByRole("option")
    .map((o) => Number((o as HTMLOptionElement).value));

describe("OTW-48 Scenario 1: Given a user opens Share on a folder, When they choose Get link", () => {
  it("Given the folder menu, When Share is clicked, Then the folder share handler fires", () => {
    const onShare = vi.fn();
    const folder = { id: FOLDER_ID, name: "Q4 Reports", updatedAt: "2026-11-01T00:00:00Z" } as FileItem;
    render(
      <MemoryRouter>
        <FolderCard folder={folder} onShare={onShare} />
      </MemoryRouter>
    );
    fireEvent.click(screen.getAllByRole("button")[0]);
    fireEvent.click(screen.getByRole("button", { name: /share/i }));
    expect(onShare).toHaveBeenCalledWith(FOLDER_ID);
  });

  it("Then the dialog opens on Get link (folders have no People tab)", async () => {
    server.use(policy(30, 90), noLinks);
    renderDialog();
    expect(screen.getByRole("button", { name: /get link/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /people/i })).not.toBeInTheDocument();
    expect(await picker()).toBeInTheDocument();
  });

  it("Then the expiry picker defaults to the workspace default from GET /workspace/share-policy", async () => {
    server.use(policy(14, 60), noLinks);
    renderDialog();
    const select = (await picker()) as HTMLSelectElement;
    expect(select.value).toBe("14");
    expect(screen.getByRole("option", { name: /14 days \(workspace default\)/ })).toBeInTheDocument();
  });

  it("Then it does not allow more than the workspace maximum and has no 'never' option", async () => {
    server.use(policy(14, 60), noLinks);
    renderDialog();
    const values = optionValues(await picker());
    expect(Math.max(...values)).toBe(60);
    expect(values.every((v) => v >= 1 && v <= 60)).toBe(true);
    expect(screen.queryByRole("option", { name: /never/i })).not.toBeInTheDocument();
    expect(screen.getByText(/up to 60 days/)).toBeInTheDocument();
  });

  it("expiryDayOptions always includes the default and max and stays within 1..max", () => {
    expect(expiryDayOptions(30, 90)).toEqual([1, 7, 14, 30, 60, 90]);
    expect(expiryDayOptions(10, 45)).toEqual([1, 7, 10, 14, 30, 45]);
    expect(expiryDayOptions(1, 1)).toEqual([1]);
  });
});

describe("OTW-48 Scenario 2: Given a link is created (POST /share-links)", () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  beforeEach(() => {
    writeText.mockClear();
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  });

  it("Then the dialog shows the link URL, a copy button and the expiry date", async () => {
    let posted: unknown;
    server.use(
      policy(30, 90),
      noLinks,
      http.post(`${API}/share-links`, async ({ request }) => {
        posted = await request.json();
        return HttpResponse.json(linkBody(), { status: 201 });
      })
    );
    renderDialog();
    await picker();
    fireEvent.click(screen.getByRole("button", { name: /create link/i }));

    const url = (await screen.findByLabelText("Share link URL")) as HTMLInputElement;
    expect(posted).toEqual({ resource_type: "folder", resource_id: FOLDER_ID, expires_in_days: 30 });
    expect(url.value).toBe(`${window.location.origin}/s/tok_abc123`);
    expect(screen.getByTestId("share-link-expiry")).toHaveTextContent(
      `Expires on ${formatExpiry("2026-12-10T12:00:00Z")}`
    );

    fireEvent.click(screen.getByRole("button", { name: /copy link/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/s/tok_abc123`));
  });

  it("shareLinkUrl uses this origin, or VITE_PUBLIC_APP_URL in native/desktop builds, never the API url", () => {
    expect(shareLinkUrl({ token: "t1" })).toBe(`${window.location.origin}/s/t1`);
    vi.stubEnv("VITE_PUBLIC_APP_URL", "https://app.example.com/");
    try {
      expect(shareLinkUrl({ token: "t1" })).toBe("https://app.example.com/s/t1");
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("Given the existing-links lookup fails, Then an error with Retry is shown instead of Create link", async () => {
    server.use(
      policy(30, 90),
      http.get(`${API}/share-links`, () => HttpResponse.json({ detail: "boom" }, { status: 500 }))
    );
    renderDialog();
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not load this folder's existing links/i);
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /create link/i })).not.toBeInTheDocument();
  });

  it("Given a link was just created, When the list refresh fails, Then the created link stays visible", async () => {
    let created = false;
    server.use(
      policy(30, 90),
      http.get(`${API}/share-links`, () =>
        created ? HttpResponse.json({ detail: "boom" }, { status: 500 }) : HttpResponse.json([])
      ),
      http.post(`${API}/share-links`, () => {
        created = true;
        return HttpResponse.json(linkBody(), { status: 201 });
      })
    );
    renderDialog();
    await picker();
    fireEvent.click(screen.getByRole("button", { name: /create link/i }));
    expect(await screen.findByLabelText("Share link URL")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByLabelText("Share link URL")).toBeInTheDocument();
    expect(screen.queryByText(/could not load this folder's existing links/i)).not.toBeInTheDocument();
  });

  it("Then the owner can change the expiry within bounds (PATCH /share-links/{id})", async () => {
    let patched: unknown;
    server.use(
      policy(30, 90),
      http.get(`${API}/share-links`, () => HttpResponse.json([linkBody()])),
      http.patch(`${API}/share-links/link-1`, async ({ request }) => {
        patched = await request.json();
        return HttpResponse.json(linkBody({ expires_at: "2026-11-17T12:00:00Z" }));
      })
    );
    renderDialog();
    expect(await screen.findByLabelText("Share link URL")).toBeInTheDocument();
    const select = await picker();
    expect(Math.max(...optionValues(select))).toBe(90);
    fireEvent.change(select, { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: /update expiry/i }));

    await waitFor(() =>
      expect(screen.getByTestId("share-link-expiry")).toHaveTextContent(
        `Expires on ${formatExpiry("2026-11-17T12:00:00Z")}`
      )
    );
    expect(patched).toEqual({ expires_in_days: 7 });
  });

  it("Given an existing link has already expired, Then it is not shown and a new link can be created", async () => {
    server.use(
      policy(30, 90),
      http.get(`${API}/share-links`, () =>
        HttpResponse.json([linkBody({ expires_at: "2020-01-01T00:00:00Z", expired_at: "2020-01-01T00:00:00Z" })])
      )
    );
    renderDialog();
    expect(await screen.findByRole("button", { name: /create link/i })).toBeInTheDocument();
    expect(screen.queryByLabelText("Share link URL")).not.toBeInTheDocument();
  });

  it("Given the server rejects the expiry with 422, Then the error is shown and no link appears", async () => {
    server.use(
      policy(30, 90),
      noLinks,
      http.post(`${API}/share-links`, () =>
        HttpResponse.json({ detail: "expires_in_days exceeds the workspace maximum of 90" }, { status: 422 })
      )
    );
    renderDialog();
    await picker();
    fireEvent.click(screen.getByRole("button", { name: /create link/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("exceeds the workspace maximum");
    expect(screen.queryByLabelText("Share link URL")).not.toBeInTheDocument();
  });

  it("Given the caller does not own the folder (403), Then an owner-only message is shown", async () => {
    server.use(
      policy(30, 90),
      noLinks,
      http.post(`${API}/share-links`, () => HttpResponse.json({ detail: "forbidden" }, { status: 403 }))
    );
    renderDialog();
    await picker();
    fireEvent.click(screen.getByRole("button", { name: /create link/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Only the folder owner");
  });
});
