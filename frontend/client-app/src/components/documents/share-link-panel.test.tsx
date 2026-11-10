import { http, HttpResponse } from "msw";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { ShareLinkPanel } from "./share-link-panel";
import { billingServer as server } from "../../test-setup";

const API = "http://localhost:3000/api/v1/documents";
const DOC_ID = "11111111-1111-1111-1111-111111111111";

const policy = {
  workspace_id: "default",
  default_expiry_days: 7,
  min_expiry_days: 1,
  max_expiry_days: 30,
  updated_by: null,
  updated_at: null,
};

function link(overrides: Record<string, unknown> = {}) {
  return {
    id: "link-1",
    document_id: DOC_ID,
    token: "tok-abc",
    created_by: "user-1",
    created_at: "2026-11-10T12:00:00Z",
    expires_at: "2099-11-17T12:00:00Z",
    workspace_id: "default",
    expired: false,
    ...overrides,
  };
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ShareLinkPanel documentId={DOC_ID} />
    </QueryClientProvider>
  );
}

function usePolicyAndLinks(links: unknown[] = []) {
  server.use(
    http.get(`${API}/share-policy`, () => HttpResponse.json(policy)),
    http.get(`${API}/${DOC_ID}/share-links`, () => HttpResponse.json(links))
  );
}

describe("ShareLinkPanel", () => {
  it("AC1: shows the workspace default and preselects it in the expiry picker", async () => {
    usePolicyAndLinks();
    renderPanel();
    expect(await screen.findByText(/Workspace default: 7 days/)).toBeInTheDocument();
    expect(screen.getByText(/Allowed range: 1 to 30 days/)).toBeInTheDocument();
    const picker = screen.getByLabelText("Link expiry") as HTMLSelectElement;
    expect(picker.value).toBe("7");
    expect(within(picker).getByRole("option", { name: /7 days \(workspace default\)/ })).toBeInTheDocument();
  });

  it("AC1: creating without choosing an expiry sends no override and shows the returned expiry", async () => {
    usePolicyAndLinks();
    let body: unknown = "unset";
    server.use(
      http.post(`${API}/${DOC_ID}/share`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(link({ id: "new", expires_at: "2026-11-17T12:00:00Z" }));
      })
    );
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Create link" }));
    const created = await screen.findByTestId("created-share-link");
    expect(body).toEqual({});
    expect(created).toHaveTextContent(`/share/${DOC_ID}?token=tok-abc`);
    expect(created).toHaveTextContent(/Expires Nov 17, 2026/);
  });

  it("AC3: a failed create clears the previously created link", async () => {
    usePolicyAndLinks();
    let calls = 0;
    server.use(
      http.post(`${API}/${DOC_ID}/share`, () => {
        calls += 1;
        return calls === 1
          ? HttpResponse.json(link({ id: "new" }))
          : HttpResponse.json({ detail: "expires_in_days must be between 1 and 30" }, { status: 422 });
      })
    );
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Create link" }));
    expect(await screen.findByTestId("created-share-link")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create link" }));
    expect(await screen.findByText(/between 1 and 30/)).toBeInTheDocument();
    expect(screen.queryByTestId("created-share-link")).not.toBeInTheDocument();
  });

  it("AC2: the picker only offers values within the workspace min and max", async () => {
    usePolicyAndLinks();
    renderPanel();
    const picker = (await screen.findByLabelText("Link expiry")) as HTMLSelectElement;
    const values = Array.from(picker.options).map((o) => Number(o.value));
    expect(values[0]).toBe(1);
    expect(values[values.length - 1]).toBe(30);
    expect(values).toHaveLength(30);
    expect(values).not.toContain(90);
  });

  it("AC2: creating with a 14-day override sends expires_in_days 14", async () => {
    usePolicyAndLinks();
    let body: unknown;
    server.use(
      http.post(`${API}/${DOC_ID}/share`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(link({ id: "new", expires_at: "2026-11-24T12:00:00Z" }));
      })
    );
    renderPanel();
    fireEvent.change(await screen.findByLabelText("Link expiry"), { target: { value: "14" } });
    fireEvent.click(screen.getByRole("button", { name: "Create link" }));
    await screen.findByTestId("created-share-link");
    expect(body).toEqual({ expires_in_days: 14 });
  });

  it("AC2: lists existing links with their expiry and changes a link's expiry to 14 days", async () => {
    let links = [link()];
    server.use(
      http.get(`${API}/share-policy`, () => HttpResponse.json(policy)),
      http.get(`${API}/${DOC_ID}/share-links`, () => HttpResponse.json(links))
    );
    let patchBody: unknown;
    server.use(
      http.patch(`${API}/${DOC_ID}/share-links/link-1`, async ({ request }) => {
        patchBody = await request.json();
        links = [link({ expires_at: "2099-12-01T12:00:00Z" })];
        return HttpResponse.json(links[0]);
      })
    );
    renderPanel();
    const row = await screen.findByTestId("share-link-link-1");
    expect(row).toHaveTextContent(/Expires Nov 17, 2099/);
    fireEvent.change(within(row).getByLabelText("New expiry for link link-1"), {
      target: { value: "14" },
    });
    fireEvent.click(within(row).getByRole("button", { name: "Change expiry" }));
    await waitFor(() => expect(patchBody).toEqual({ expires_in_days: 14 }));
    expect(await screen.findByText(/Expires Dec 1, 2099/)).toBeInTheDocument();
  });

  it("AC3: surfaces the 422 message naming the allowed range", async () => {
    usePolicyAndLinks();
    server.use(
      http.post(`${API}/${DOC_ID}/share`, () =>
        HttpResponse.json(
          { detail: "expires_in_days must be between 1 and 30 days" },
          { status: 422 }
        )
      )
    );
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Create link" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "expires_in_days must be between 1 and 30 days"
    );
    expect(screen.queryByTestId("created-share-link")).not.toBeInTheDocument();
  });

  it("AC4: an expired link is marked expired and cannot be extended", async () => {
    usePolicyAndLinks([link({ expires_at: "2026-11-01T12:00:00Z", expired: true })]);
    renderPanel();
    const row = await screen.findByTestId("share-link-link-1");
    expect(row).toHaveTextContent(/Expired Nov 1, 2026/);
    expect(within(row).queryByRole("button", { name: "Change expiry" })).not.toBeInTheDocument();
    expect(within(row).queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("AC4: a 410 when changing expiry is shown and the link is not extended", async () => {
    usePolicyAndLinks([link()]);
    server.use(
      http.patch(`${API}/${DOC_ID}/share-links/link-1`, () =>
        HttpResponse.json({ detail: "This share link has expired" }, { status: 410 })
      )
    );
    renderPanel();
    const row = await screen.findByTestId("share-link-link-1");
    fireEvent.click(within(row).getByRole("button", { name: "Change expiry" }));
    expect(await within(row).findByRole("alert")).toHaveTextContent("This share link has expired");
  });
});
