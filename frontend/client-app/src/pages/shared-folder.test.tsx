import { http, HttpResponse } from "msw";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import SharedFolderPage from "./shared-folder";
import { billingServer as server } from "../test-setup";

const SHARED_URL = "http://localhost:3000/api/v1/folder-share-links/shared";
const EXPIRED = "This link has expired, ask the owner for a new one";

function renderPage(token = "tok-123") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/shared/folders/${token}`]}>
        <Routes>
          <Route path="/shared/folders/:token" element={<SharedFolderPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("SharedFolderPage", () => {
  // US1: Given a valid, unexpired token, When anyone opens the link, Then they get a read-only
  // view of the folder's contents.
  it("US1 valid token: renders the folder name and its files read-only", async () => {
    let requestedToken: string | null = null;
    server.use(
      http.get(SHARED_URL, ({ request }) => {
        requestedToken = new URL(request.url).searchParams.get("token");
        return HttpResponse.json({
          folder: { id: "f1", name: "Q4 Reports" },
          files: [
            { id: "1", name: "summary.pdf", size: 2048, mime_type: "application/pdf", updated_at: "2026-11-09T10:00:00Z" },
            { id: "2", name: "budget.xlsx", size: 1048576, mime_type: "application/vnd.ms-excel", updated_at: "2026-11-08T10:00:00Z" },
          ],
          expires_at: "2026-12-10T10:00:00Z",
        });
      })
    );
    renderPage();

    expect(await screen.findByRole("heading", { name: "Q4 Reports" })).toBeInTheDocument();
    expect(requestedToken).toBe("tok-123");
    expect(screen.getByText("summary.pdf")).toBeInTheDocument();
    expect(screen.getByText("budget.xlsx")).toBeInTheDocument();
    expect(screen.getByText("2 KB")).toBeInTheDocument();
    expect(screen.getByText("1 MB")).toBeInTheDocument();
    expect(screen.getByText(/view only/i)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText(EXPIRED)).not.toBeInTheDocument();
  });

  // US4: Given a link's expires_at is in the past, When anyone opens it, Then the API returns 410
  // and the client shows the expired-link page.
  it("US4 expired link (410 link_expired): shows the expired message", async () => {
    server.use(http.get(SHARED_URL, () => HttpResponse.json({ detail: "link_expired" }, { status: 410 })));
    renderPage();
    expect(await screen.findByRole("heading", { name: EXPIRED })).toBeInTheDocument();
  });

  // US4: Given a link has been revoked, When anyone opens it, Then 410 with the same page.
  it("US4 revoked link (410 link_revoked): shows the same expired message", async () => {
    server.use(http.get(SHARED_URL, () => HttpResponse.json({ detail: "link_revoked" }, { status: 410 })));
    renderPage();
    expect(await screen.findByRole("heading", { name: EXPIRED })).toBeInTheDocument();
  });

  // US4: Given an unknown or tampered token, Then the API returns 404, not 410.
  it("US4 unknown token (404): shows link not found, not the expired message", async () => {
    server.use(http.get(SHARED_URL, () => HttpResponse.json({ detail: "not_found" }, { status: 404 })));
    renderPage("tampered");
    expect(await screen.findByRole("heading", { name: "Link not found" })).toBeInTheDocument();
    expect(screen.queryByText(EXPIRED)).not.toBeInTheDocument();
  });

  it("server error: shows a generic error, not the expired message", async () => {
    server.use(http.get(SHARED_URL, () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
    renderPage();
    expect(await screen.findByRole("heading", { name: "Something went wrong" })).toBeInTheDocument();
    expect(screen.queryByText(EXPIRED)).not.toBeInTheDocument();
  });
});
