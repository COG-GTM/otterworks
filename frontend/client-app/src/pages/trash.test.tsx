import type { ReactNode } from "react";
import { http, HttpResponse } from "msw";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import TrashPage from "./trash";
import { billingServer as server } from "../test-setup";

vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

const API = "http://localhost:3000/api/v1";

const ITEMS = [
  { id: "file-a", name: "alpha.txt" },
  { id: "file-b", name: "beta.txt" },
  { id: "file-c", name: "gamma.txt" },
];

function rawFile({ id, name }: { id: string; name: string }) {
  return {
    id,
    name,
    mime_type: "text/plain",
    size_bytes: 1024,
    folder_id: null,
    owner_id: "user-1",
    is_trashed: true,
  };
}

function setupTrashServer() {
  const trashed = new Set(ITEMS.map((item) => item.id));
  const pendingRestores = new Map<string, () => void>();

  server.use(
    http.get(`${API}/files/trash`, () => {
      const files = ITEMS.filter((item) => trashed.has(item.id)).map(rawFile);
      return HttpResponse.json({ files, total: files.length, page: 1, page_size: 50 });
    }),
    http.post(`${API}/files/:id/restore`, async ({ params }) => {
      const id = params.id as string;
      await new Promise<void>((resolve) => pendingRestores.set(id, resolve));
      trashed.delete(id);
      return new HttpResponse(null, { status: 204 });
    }),
  );

  return {
    finishRestore: (id: string) => {
      const resolve = pendingRestores.get(id);
      if (!resolve) throw new Error(`No pending restore for ${id}`);
      pendingRestores.delete(id);
      resolve();
    },
    hasPendingRestore: (id: string) => pendingRestores.has(id),
  };
}

function renderTrash() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <TrashPage />
    </QueryClientProvider>,
  );
}

function restoreButton(name: string) {
  const row = screen.getByText(name).closest("div.flex.items-center.gap-4") as HTMLElement;
  return within(row).getByRole("button", { name: /restore/i });
}

describe("Trash page restore", () => {
  it("only disables Restore on the row being restored", async () => {
    const api = setupTrashServer();
    renderTrash();
    expect(await screen.findByText("alpha.txt")).toBeInTheDocument();

    fireEvent.click(restoreButton("alpha.txt"));

    await waitFor(() => expect(restoreButton("alpha.txt")).toBeDisabled());
    expect(restoreButton("beta.txt")).toBeEnabled();
    expect(restoreButton("gamma.txt")).toBeEnabled();

    await waitFor(() => expect(api.hasPendingRestore("file-a")).toBe(true));
    api.finishRestore("file-a");
    await waitFor(() => expect(screen.queryByText("alpha.txt")).not.toBeInTheDocument());
  });

  it("restores two items back to back and removes both from the list", async () => {
    const api = setupTrashServer();
    renderTrash();
    expect(await screen.findByText("alpha.txt")).toBeInTheDocument();

    fireEvent.click(restoreButton("alpha.txt"));
    await waitFor(() => expect(restoreButton("alpha.txt")).toBeDisabled());
    fireEvent.click(restoreButton("beta.txt"));
    await waitFor(() => expect(restoreButton("beta.txt")).toBeDisabled());
    expect(restoreButton("alpha.txt")).toBeDisabled();
    expect(restoreButton("gamma.txt")).toBeEnabled();

    await waitFor(() => {
      expect(api.hasPendingRestore("file-a")).toBe(true);
      expect(api.hasPendingRestore("file-b")).toBe(true);
    });

    api.finishRestore("file-a");
    await waitFor(() => expect(screen.queryByText("alpha.txt")).not.toBeInTheDocument());
    expect(restoreButton("beta.txt")).toBeDisabled();
    expect(restoreButton("gamma.txt")).toBeEnabled();

    api.finishRestore("file-b");
    await waitFor(() => expect(screen.queryByText("beta.txt")).not.toBeInTheDocument());
    expect(screen.getByText("gamma.txt")).toBeInTheDocument();
    expect(restoreButton("gamma.txt")).toBeEnabled();
  });
});
