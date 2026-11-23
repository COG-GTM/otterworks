import type { ReactNode } from "react";
import { http, HttpResponse } from "msw";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import DocumentsPage from "./documents";
import { billingServer } from "../test-setup";

vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

// Mirrors document-service's GET /documents: `size` (default 20, max 100), other params ignored.
function serveDocuments(count: number) {
  const requests: URLSearchParams[] = [];
  billingServer.use(
    http.get("http://localhost:3000/api/v1/documents", ({ request }) => {
      const params = new URL(request.url).searchParams;
      requests.push(params);
      const page = Number(params.get("page") ?? 1);
      const size = Math.min(Number(params.get("size") ?? 20), 100);
      const start = (page - 1) * size;
      const items = Array.from(
        { length: Math.max(0, Math.min(size, count - start)) },
        (_, i) => {
          const n = start + i + 1;
          return {
            id: `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`,
            title: `Doc ${n}`,
            content: "",
            content_type: "text/markdown",
            owner_id: "00000000-0000-0000-0000-0000000000aa",
            folder_id: null,
            is_deleted: false,
            is_template: false,
            word_count: 0,
            version: 1,
            created_at: "2026-11-01T00:00:00Z",
            updated_at: "2026-11-01T00:00:00Z",
          };
        },
      );
      return HttpResponse.json({ items, total: count, page, size, pages: Math.ceil(count / size) });
    }),
  );
  return requests;
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DocumentsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Documents page", () => {
  it("lists more than 20 documents", async () => {
    const requests = serveDocuments(25);
    renderPage();

    expect(await screen.findByText("Doc 25")).toBeInTheDocument();
    expect(screen.getAllByText(/^Doc \d+$/)).toHaveLength(25);
    expect(requests[0].get("size")).toBe("50");
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("loads the next page on demand", async () => {
    serveDocuments(60);
    renderPage();

    expect(await screen.findByText("Doc 50")).toBeInTheDocument();
    expect(screen.queryByText("Doc 51")).not.toBeInTheDocument();
    expect(screen.getByText("Showing 50 of 60 documents")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("Doc 60")).toBeInTheDocument();
    expect(screen.getAllByText(/^Doc \d+$/)).toHaveLength(60);
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });
});
