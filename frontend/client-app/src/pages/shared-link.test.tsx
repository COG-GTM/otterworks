import { http, HttpResponse } from "msw";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { billingServer as server } from "../test-setup";
import App from "../App";
import SharedLinkPage from "./shared-link";

const API = "http://localhost:3000/api/v1";

function renderAt(token: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/s/${token}`]}>
        <Routes>
          <Route path="/s/:token" element={<SharedLinkPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const resolved = http.get(`${API}/share-links/resolve/good-token`, () =>
  HttpResponse.json({
    resource_type: "folder",
    folder: { id: "f1", name: "Q4 Reports" },
    files: [
      { id: "a", name: "budget.xlsx", mime_type: "application/vnd.ms-excel", size_bytes: 2048, updated_at: "2026-11-01T00:00:00Z" },
      { id: "b", name: "summary.pdf", mime_type: "application/pdf", size_bytes: 1024, updated_at: "2026-11-02T00:00:00Z" },
    ],
    expires_at: "2026-12-10T12:00:00Z",
  })
);

describe("OTW-48 Scenario 3: Given a recipient opens a link and resolve returns 410", () => {
  it("Then the client-app shows 'This link has expired' and tells them to ask the owner", async () => {
    server.use(
      http.get(`${API}/share-links/resolve/old-token`, () =>
        HttpResponse.json({ error: "link_expired", expired_at: "2026-11-01T00:00:00Z" }, { status: 410 })
      )
    );
    renderAt("old-token");
    expect(await screen.findByRole("heading", { name: "This link has expired" })).toBeInTheDocument();
    expect(screen.getByText(/ask the owner/i)).toBeInTheDocument();
    expect(screen.queryByText("Q4 Reports")).not.toBeInTheDocument();
  });

  it("Given an unknown token (404), Then a 'Link not found' page is shown", async () => {
    server.use(
      http.get(`${API}/share-links/resolve/missing`, () => HttpResponse.json({ error: "not_found" }, { status: 404 }))
    );
    renderAt("missing");
    expect(await screen.findByRole("heading", { name: "Link not found" })).toBeInTheDocument();
  });

  it("Given a signed-out visitor, Then /s/:token is a public route in App", async () => {
    localStorage.removeItem("otter_access_token");
    server.use(
      http.get(`${API}/share-links/resolve/old-token`, () =>
        HttpResponse.json({ error: "link_expired", expired_at: "2026-11-01T00:00:00Z" }, { status: 410 })
      )
    );
    render(
      <MemoryRouter initialEntries={["/s/old-token"]}>
        <App />
      </MemoryRouter>
    );
    expect(await screen.findByRole("heading", { name: "This link has expired" })).toBeInTheDocument();
  });
});

describe("OTW-48 Scenario 4: Given a valid link", () => {
  it("Then the recipient sees the folder contents read-only", async () => {
    server.use(resolved);
    renderAt("good-token");
    expect(await screen.findByRole("heading", { name: "Q4 Reports" })).toBeInTheDocument();
    expect(screen.getByText("budget.xlsx")).toBeInTheDocument();
    expect(screen.getByText("summary.pdf")).toBeInTheDocument();
    expect(screen.getByText("View only")).toBeInTheDocument();
  });

  it("Then there are no upload, rename or delete actions", async () => {
    server.use(resolved);
    const { container } = renderAt("good-token");
    await screen.findByRole("heading", { name: "Q4 Reports" });
    expect(screen.queryByRole("button", { name: /upload|rename|delete|new folder/i })).not.toBeInTheDocument();
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(container.querySelector('input[type="file"]')).toBeNull();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
