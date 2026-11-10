import { http, HttpResponse } from "msw";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import SharedDocumentPage from "./shared-document";
import { billingServer as server } from "../test-setup";

const DOC_ID = "22222222-2222-2222-2222-222222222222";
const SHARED_URL = "http://localhost:3000/api/v1/documents/shared";

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/share/:documentId" element={<SharedDocumentPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("SharedDocumentPage", () => {
  it("AC5: a valid link opens the document read-only", async () => {
    let query: URLSearchParams | undefined;
    server.use(
      http.get(SHARED_URL, ({ request }) => {
        query = new URL(request.url).searchParams;
        return HttpResponse.json({
          id: DOC_ID,
          title: "Quarterly plan",
          content: "<p>Hello shared world</p>",
          owner_id: "owner-1",
          updated_at: "2026-11-10T12:00:00Z",
        });
      })
    );
    renderAt(`/share/${DOC_ID}?token=tok-123`);
    expect(await screen.findByRole("heading", { name: "Quarterly plan" })).toBeInTheDocument();
    expect(screen.getByText("View only")).toBeInTheDocument();
    expect(await screen.findByText("Hello shared world")).toBeInTheDocument();
    expect(screen.getByTestId("shared-document-content").querySelector("[contenteditable='true']")).toBeNull();
    expect(query?.get("document_id")).toBe(DOC_ID);
    expect(query?.get("token")).toBe("tok-123");
  });

  it("AC4: HTTP 410 shows the 'This link has expired' page", async () => {
    server.use(
      http.get(SHARED_URL, () =>
        HttpResponse.json({ detail: "This share link has expired" }, { status: 410 })
      )
    );
    renderAt(`/share/${DOC_ID}?token=old-token`);
    expect(await screen.findByRole("heading", { name: "This link has expired" })).toBeInTheDocument();
    expect(screen.getByText(/Ask the document owner to send you a new link/)).toBeInTheDocument();
  });

  it("HTTP 403 shows an invalid-link message", async () => {
    server.use(
      http.get(SHARED_URL, () => HttpResponse.json({ detail: "Invalid share token" }, { status: 403 }))
    );
    renderAt(`/share/${DOC_ID}?token=bad`);
    expect(await screen.findByRole("heading", { name: "This link is not valid" })).toBeInTheDocument();
  });

  it("a link without a token is invalid and makes no request", async () => {
    renderAt(`/share/${DOC_ID}`);
    expect(await screen.findByRole("heading", { name: "This link is not valid" })).toBeInTheDocument();
  });
});
