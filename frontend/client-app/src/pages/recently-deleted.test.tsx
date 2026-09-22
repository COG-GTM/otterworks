import { http, HttpResponse } from "msw";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import RecentlyDeletedPage from "./recently-deleted";
import { QueryProvider } from "@/providers/query-provider";
import { billingServer } from "../test-setup";

const API = "http://localhost:3000/api/v1";

const trashResponse = {
  items: [
    {
      id: "11111111-1111-1111-1111-111111111111",
      name: "quarterly-report.pdf",
      mime_type: "application/pdf",
      size_bytes: 2048,
      is_folder: false,
      original_path: "/Reports/2026",
      original_location_exists: true,
      deleted_by: "22222222-2222-2222-2222-222222222222",
      deleted_at: new Date().toISOString(),
      purge_at: new Date().toISOString(),
    },
    {
      id: "33333333-3333-3333-3333-333333333333",
      name: "Archive",
      mime_type: null,
      size_bytes: 0,
      is_folder: true,
      original_path: "/Gone",
      original_location_exists: false,
      deleted_by: null,
      deleted_at: new Date().toISOString(),
      purge_at: new Date().toISOString(),
    },
  ],
  total: 2,
  page: 1,
  page_size: 50,
  retention_days: 30,
};

function renderPage() {
  return render(
    <MemoryRouter>
      <QueryProvider>
        <RecentlyDeletedPage />
      </QueryProvider>
    </MemoryRouter>
  );
}

describe("Recently deleted", () => {
  it("lists deleted files and folders with their original location", async () => {
    billingServer.use(
      http.get(`${API}/files/trash`, () => HttpResponse.json(trashResponse)),
      http.get(`${API}/auth/users/by-id/:id`, () =>
        HttpResponse.json({ id: "22222222-2222-2222-2222-222222222222", email: "otter@example.com", display_name: "Olive Otter" })
      ),
      http.get(`${API}/*`, () => HttpResponse.json({}))
    );

    renderPage();

    expect(await screen.findByRole("heading", { name: "Recently deleted" })).toBeInTheDocument();
    expect(await screen.findByText("quarterly-report.pdf")).toBeInTheDocument();
    expect(screen.getByText(/In \/Reports\/2026/)).toBeInTheDocument();
    expect(screen.getByText("Archive")).toBeInTheDocument();
    expect(screen.getByText(/folder no longer exists/)).toBeInTheDocument();
    expect(screen.getAllByTitle("Restore")).toHaveLength(2);
    expect(screen.getAllByTitle("Delete permanently")).toHaveLength(2);
    expect(await screen.findByText(/by Olive Otter/)).toBeInTheDocument();
  });

  it("loads further pages of deleted items on demand", async () => {
    billingServer.use(
      http.get(`${API}/files/trash`, ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get("page") ?? 1);
        return HttpResponse.json({
          items: [{ ...trashResponse.items[0], id: `page-${page}`, name: `page-${page}.pdf` }],
          total: 2,
          page,
          page_size: 1,
          retention_days: 30,
        });
      }),
      http.get(`${API}/*`, () => HttpResponse.json({}))
    );

    renderPage();

    expect(await screen.findByText("page-1.pdf")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /Load more/ }));

    expect(await screen.findByText("page-2.pdf")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Load more/ })).not.toBeInTheDocument();
  });

  it("shows an empty state when nothing was deleted recently", async () => {
    billingServer.use(
      http.get(`${API}/files/trash`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50, retention_days: 30 })
      ),
      http.get(`${API}/*`, () => HttpResponse.json({}))
    );

    renderPage();

    expect(await screen.findByText("Nothing recently deleted")).toBeInTheDocument();
  });
});
