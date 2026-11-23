import type { ReactNode } from "react";
import { delay, http, HttpResponse } from "msw";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import DocumentsPage from "./documents";
import { billingServer } from "../test-setup";
import { useAuthStore } from "@/stores/auth-store";
import type { User } from "@/types";

vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

interface ServeOptions {
  title?: (n: number) => string;
  failPage?: number;
  delayMs?: number;
}

// Mirrors document-service's GET /documents: `size` (default 20, max 100), other params ignored.
function serveDocuments(count: number, { title = (n) => `Doc ${n}`, failPage, delayMs }: ServeOptions = {}) {
  const requests: URLSearchParams[] = [];
  billingServer.use(
    http.get("http://localhost:3000/api/v1/documents", async ({ request }) => {
      const params = new URL(request.url).searchParams;
      requests.push(params);
      const page = Number(params.get("page") ?? 1);
      if (delayMs) await delay(delayMs);
      if (page === failPage) return HttpResponse.json({ detail: "boom" }, { status: 500 });
      const size = Math.min(Number(params.get("size") ?? 20), 100);
      const start = (page - 1) * size;
      const items = Array.from(
        { length: Math.max(0, Math.min(size, count - start)) },
        (_, i) => {
          const n = start + i + 1;
          return {
            id: `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`,
            title: title(n),
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

function user(id: string): User {
  return { id, email: `${id}@example.com`, displayName: id };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DocumentsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return queryClient;
}

afterEach(() => useAuthStore.setState({ user: null, isAuthenticated: false }));

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
    expect(screen.getByText("Loaded 50 of 60 documents")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("Doc 60")).toBeInTheDocument();
    expect(screen.getAllByText(/^Doc \d+$/)).toHaveLength(60);
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("reports a failed Load more and lets the user retry", async () => {
    serveDocuments(60, { failPage: 2 });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Load more" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load more documents");
    expect(screen.getAllByText(/^Doc \d+$/)).toHaveLength(50);

    serveDocuments(60);
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("Doc 60")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps Load more disabled while the list is refreshing", async () => {
    serveDocuments(60);
    const queryClient = renderPage();
    const loadMore = await screen.findByRole("button", { name: "Load more" });
    expect(loadMore).toBeEnabled();

    serveDocuments(60, { delayMs: 200 });
    act(() => {
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    });

    await waitFor(() => expect(loadMore).toBeDisabled());
    await waitFor(() => expect(loadMore).toBeEnabled());
  });

  it("does not show the previous account's documents after switching accounts", async () => {
    useAuthStore.setState({ user: user("alice"), isAuthenticated: true });
    serveDocuments(3, { title: (n) => `Alice doc ${n}` });
    renderPage();
    expect(await screen.findByText("Alice doc 3")).toBeInTheDocument();

    serveDocuments(2, { title: (n) => `Bob doc ${n}` });
    act(() => useAuthStore.setState({ user: user("bob"), isAuthenticated: true }));

    expect(await screen.findByText("Bob doc 2")).toBeInTheDocument();
    expect(screen.queryByText("Alice doc 3")).not.toBeInTheDocument();
  });
});
