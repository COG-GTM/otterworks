import { http, HttpResponse } from "msw";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import DocumentsPage from "./documents";
import { billingServer as server } from "../test-setup";

const DOCUMENTS_URL = "http://localhost:3000/api/v1/documents";

const doc = {
  id: "doc-1",
  title: "Quarterly plan",
  content: "",
  owner_id: "user-1",
  owner_name: "Otter",
  collaborators: [],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DocumentsPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("Documents page", () => {
  it("shows an error state instead of the empty state when loading fails", async () => {
    server.use(
      http.get(DOCUMENTS_URL, () =>
        HttpResponse.json({ error: "unavailable" }, { status: 503 })
      )
    );
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Documents could not be loaded."
    );
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByText("No documents yet")).not.toBeInTheDocument();
    expect(screen.queryByText("Create document")).not.toBeInTheDocument();
  });

  it("re-runs the query when Retry is clicked", async () => {
    let attempts = 0;
    server.use(
      http.get(DOCUMENTS_URL, () => {
        attempts += 1;
        return attempts === 1
          ? HttpResponse.json({ error: "unavailable" }, { status: 503 })
          : HttpResponse.json({ items: [doc], total: 1, page: 1, page_size: 50 });
      })
    );
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Quarterly plan")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it("keeps cached documents visible when a refresh fails", async () => {
    server.use(
      http.get(DOCUMENTS_URL, () =>
        HttpResponse.json({ error: "unavailable" }, { status: 503 })
      )
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(["documents", "list"], {
      items: [doc],
      total: 1,
      page: 1,
      page_size: 50,
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <DocumentsPage />
        </MemoryRouter>
      </QueryClientProvider>
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Documents could not be refreshed."
    );
    expect(screen.getByText("Quarterly plan")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByText("Documents could not be loaded.")).not.toBeInTheDocument();
  });

  it("shows the error state when refreshing a cached empty list fails", async () => {
    server.use(
      http.get(DOCUMENTS_URL, () =>
        HttpResponse.json({ error: "unavailable" }, { status: 503 })
      )
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(["documents", "list"], {
      items: [],
      total: 0,
      page: 1,
      page_size: 50,
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <DocumentsPage />
        </MemoryRouter>
      </QueryClientProvider>
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Documents could not be loaded."
    );
    expect(screen.queryByText("No documents yet")).not.toBeInTheDocument();
    expect(screen.queryByText("Documents could not be refreshed.", { exact: false })).not.toBeInTheDocument();
  });

  it("still shows the empty state for a successful empty list", async () => {
    server.use(
      http.get(DOCUMENTS_URL, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50 })
      )
    );
    renderPage();
    expect(await screen.findByText("No documents yet")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
