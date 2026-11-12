import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { FileItem, PaginatedResponse } from "@/types";

const getTrashed = vi.fn<() => Promise<PaginatedResponse<FileItem>>>();

vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("@/lib/api", () => ({
  filesApi: {
    getTrashed: () => getTrashed(),
    restore: vi.fn(),
    permanentDelete: vi.fn(),
  },
}));

import TrashPage from "./trash";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TrashPage />
    </QueryClientProvider>
  );
}

const trashedFile = {
  id: "f1",
  name: "old-report.pdf",
  mimeType: "application/pdf",
  size: 2048,
  isFolder: false,
} as FileItem;

describe("Trash page", () => {
  afterEach(() => getTrashed.mockReset());

  it("shows a loader while trash is loading", () => {
    getTrashed.mockReturnValue(new Promise(() => {}));
    const { container } = renderPage();
    expect(container.querySelector(".animate-spin")).toBeInTheDocument();
    expect(screen.queryByText("Trash is empty")).not.toBeInTheDocument();
  });

  it("shows the empty state when trash has no items", async () => {
    getTrashed.mockResolvedValue({ data: [], total: 0 } as unknown as PaginatedResponse<FileItem>);
    renderPage();
    expect(await screen.findByText("Trash is empty")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Empty Trash/ })).not.toBeInTheDocument();
  });

  it("lists trashed items with restore and delete actions", async () => {
    getTrashed.mockResolvedValue({
      data: [trashedFile],
      total: 1,
    } as unknown as PaginatedResponse<FileItem>);
    renderPage();
    expect(await screen.findByText("old-report.pdf")).toBeInTheDocument();
    expect(screen.getByTitle("Restore")).toBeInTheDocument();
    expect(screen.getByTitle("Delete permanently")).toBeInTheDocument();
    expect(screen.queryByText("Trash is empty")).not.toBeInTheDocument();
  });
});
