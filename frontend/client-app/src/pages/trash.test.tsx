import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FileItem } from "@/types";
import TrashPage from "./trash";

const api = vi.hoisted(() => ({
  getTrashed: vi.fn(),
  restore: vi.fn(),
  permanentDelete: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ filesApi: api }));
vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

function trashedFile(id: string, name: string): FileItem {
  return {
    id,
    name,
    mimeType: "text/plain",
    size: 1024,
    parentId: null,
    ownerId: "owner-1",
    ownerName: "Owner",
    isFolder: false,
    isTrashed: true,
    path: `/${name}`,
    sharedWith: [],
    tags: [],
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    versions: [],
  };
}

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

const files = [
  trashedFile("f1", "alpha.txt"),
  trashedFile("f2", "bravo.txt"),
  trashedFile("f3", "charlie.txt"),
];
let restored: Set<string>;

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <TrashPage />
    </QueryClientProvider>
  );
}

function restoreButtons() {
  return screen.getAllByRole("button", { name: "Restore" });
}

beforeEach(() => {
  restored = new Set();
  api.getTrashed.mockReset().mockImplementation(async () => {
    const data = files.filter((f) => !restored.has(f.id));
    return { data, total: data.length, page: 1, pageSize: 50 };
  });
  api.restore.mockReset();
  api.permanentDelete.mockReset();
});

describe("Trash restore", () => {
  it("only disables Restore on the row being restored", async () => {
    const pending = deferred();
    api.restore.mockReturnValue(pending.promise);
    renderPage();
    await screen.findByText("alpha.txt");

    fireEvent.click(restoreButtons()[0]);

    await waitFor(() => expect(restoreButtons()[0]).toBeDisabled());
    expect(restoreButtons()[1]).toBeEnabled();
    expect(restoreButtons()[2]).toBeEnabled();
    expect(api.restore.mock.calls[0][0]).toBe("f1");

    pending.resolve();
  });

  it("restores two items back to back and removes both from the list", async () => {
    const calls: Record<string, ReturnType<typeof deferred>> = {};
    api.restore.mockImplementation((id: string) => {
      calls[id] = deferred();
      return calls[id].promise.then(() => {
        restored.add(id);
      });
    });
    renderPage();
    await screen.findByText("alpha.txt");

    fireEvent.click(restoreButtons()[0]);
    await waitFor(() => expect(restoreButtons()[0]).toBeDisabled());
    expect(restoreButtons()[1]).toBeEnabled();
    fireEvent.click(restoreButtons()[1]);

    await waitFor(() => expect(restoreButtons()[1]).toBeDisabled());
    expect(restoreButtons()[2]).toBeEnabled();
    expect(api.restore.mock.calls.map(([id]) => id)).toEqual(["f1", "f2"]);

    calls.f1.resolve();
    calls.f2.resolve();

    await waitFor(() => {
      expect(screen.queryByText("alpha.txt")).not.toBeInTheDocument();
      expect(screen.queryByText("bravo.txt")).not.toBeInTheDocument();
    });
    expect(screen.getByText("charlie.txt")).toBeInTheDocument();
    expect(restoreButtons()[0]).toBeEnabled();
  });
});
