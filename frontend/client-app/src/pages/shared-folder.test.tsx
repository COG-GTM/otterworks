import { http, HttpResponse } from "msw";
import { fireEvent, screen } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import SharedFolderPage from "./shared-folder";
import SharedFolderDocumentPage from "./shared-folder-document";
import { billingServer as server } from "../test-setup";
import { API, renderWithProviders } from "../test/render";

const TOKEN = "tok_abc";

function renderRecipient(route = `/shared-folder/${TOKEN}`) {
  return renderWithProviders(
    <Routes>
      <Route path="/shared-folder/:token" element={<SharedFolderPage />} />
      <Route path="/shared-folder/:token/documents/:documentId" element={<SharedFolderDocumentPage />} />
    </Routes>,
    { route }
  );
}

describe("Shared folder recipient view", () => {
  it("lists the folder's documents and opens one read-only", async () => {
    server.use(
      http.get(`${API}/documents/shared-folders/${TOKEN}`, () =>
        HttpResponse.json({
          folder_id: "f-1",
          expires_at: "2026-12-10T10:00:00Z",
          documents: [
            { id: "d-1", title: "Roadmap", updated_at: "2026-11-01T10:00:00Z" },
            { id: "d-2", title: "Budget", updated_at: "2026-11-02T10:00:00Z" },
          ],
        })
      ),
      http.get(`${API}/documents/shared-folders/${TOKEN}/documents/d-1`, () =>
        HttpResponse.json({
          id: "d-1",
          title: "Roadmap",
          content: "<p>Ship expiring links in Q4.</p>",
          content_type: "text/html",
          updated_at: "2026-11-01T10:00:00Z",
        })
      )
    );
    renderRecipient();

    expect(await screen.findByRole("heading", { name: "Shared folder" })).toBeInTheDocument();
    expect(screen.getByText("View only")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Budget/ })).toHaveAttribute(
      "href",
      `/shared-folder/${TOKEN}/documents/d-2`
    );

    fireEvent.click(screen.getByRole("link", { name: /Roadmap/ }));
    expect(await screen.findByRole("heading", { name: "Roadmap" })).toBeInTheDocument();
    expect(await screen.findByText("Ship expiring links in Q4.")).toBeInTheDocument();
    expect(screen.getByText("Read-only")).toBeInTheDocument();
    const body = screen.getByTestId("read-only-document");
    expect(body).toHaveAttribute("contenteditable", "false");
    expect(screen.queryByRole("button", { name: /save/i })).not.toBeInTheDocument();
  });

  it("shows plain-text document bodies line by line without rendering HTML", async () => {
    server.use(
      http.get(`${API}/documents/shared-folders/${TOKEN}/documents/d-3`, () =>
        HttpResponse.json({
          id: "d-3",
          title: "Notes",
          content: "line one\n<img src=x onerror=alert(1)>",
          updated_at: "2026-11-01T10:00:00Z",
        })
      )
    );
    renderRecipient(`/shared-folder/${TOKEN}/documents/d-3`);
    expect(await screen.findByText("line one")).toBeInTheDocument();
    expect(document.querySelector("img[src=x]")).toBeNull();
  });

  it('shows "This link has expired" when the API returns 410', async () => {
    server.use(
      http.get(`${API}/documents/shared-folders/${TOKEN}`, () =>
        HttpResponse.json({ detail: "Share link expired" }, { status: 410 })
      )
    );
    renderRecipient();
    expect(await screen.findByRole("heading", { name: "This link has expired" })).toBeInTheDocument();
    expect(screen.queryByText("Shared folder")).not.toBeInTheDocument();
  });

  it("shows the expired page for a revoked link (410) with the revoked hint", async () => {
    server.use(
      http.get(`${API}/documents/shared-folders/${TOKEN}`, () =>
        HttpResponse.json({ detail: "Share link revoked" }, { status: 410 })
      )
    );
    renderRecipient();
    expect(await screen.findByRole("heading", { name: "This link has expired" })).toBeInTheDocument();
    expect(screen.getByText("The owner turned off this link.")).toBeInTheDocument();
  });

  it("shows the expired page when a document is opened after the link expired (410)", async () => {
    server.use(
      http.get(`${API}/documents/shared-folders/${TOKEN}/documents/d-1`, () =>
        HttpResponse.json({ detail: "Share link expired" }, { status: 410 })
      )
    );
    renderRecipient(`/shared-folder/${TOKEN}/documents/d-1`);
    expect(await screen.findByRole("heading", { name: "This link has expired" })).toBeInTheDocument();
  });

  it("shows not found for an unknown token (404)", async () => {
    server.use(
      http.get(`${API}/documents/shared-folders/${TOKEN}`, () =>
        HttpResponse.json({ detail: "Not found" }, { status: 404 })
      )
    );
    renderRecipient();
    expect(await screen.findByRole("heading", { name: "Link not found" })).toBeInTheDocument();
  });
});
