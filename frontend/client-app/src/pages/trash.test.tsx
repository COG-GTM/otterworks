import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FileItem, PaginatedResponse } from "@/types";

const { filesApiMock, toastMock } = vi.hoisted(() => ({
  filesApiMock: {
    getTrashed: vi.fn(),
    restore: vi.fn(),
    permanentDelete: vi.fn(),
  },
  toastMock: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api", () => ({ filesApi: filesApiMock }));
vi.mock("react-hot-toast", () => ({ default: toastMock }));
vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

import TrashPage from "./trash";

function makeItem(id: string, name: string): FileItem {
  const now = new Date().toISOString();
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
    versions: [],
    trashedAt: now,
    createdAt: now,
    updatedAt: now,
  };
}

function page(items: FileItem[]): PaginatedResponse<FileItem> {
  return { data: items, total: items.length, page: 1, pageSize: 50, hasMore: false };
}

let trashed: FileItem[] = [];

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

beforeEach(() => {
  vi.clearAllMocks();
  trashed = [makeItem("f1", "report.txt"), makeItem("f2", "notes.txt"), makeItem("f3", "todo.txt")];
  filesApiMock.getTrashed.mockImplementation(async () => page([...trashed]));
  filesApiMock.restore.mockImplementation(async (id: string) => {
    trashed = trashed.filter((item) => item.id !== id);
  });
  filesApiMock.permanentDelete.mockImplementation(async (id: string) => {
    trashed = trashed.filter((item) => item.id !== id);
  });
});

describe("Trash page - Restore all", () => {
  it("shows Restore all next to Empty Trash and asks for confirmation before restoring", async () => {
    renderPage();
    const restoreAll = await screen.findByRole("button", { name: /restore all/i });
    expect(screen.getByRole("button", { name: /empty trash/i })).toBeInTheDocument();

    fireEvent.click(restoreAll);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("This will restore all 3 items in trash");
    expect(filesApiMock.restore).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(filesApiMock.restore).not.toHaveBeenCalled();
  });

  it("restores every item after confirming and shows a toast with the count", async () => {
    let releaseRestore: () => void = () => {};
    const restoreGate = new Promise<void>((resolve) => {
      releaseRestore = resolve;
    });
    filesApiMock.restore.mockImplementation(async (id: string) => {
      await restoreGate;
      trashed = trashed.filter((item) => item.id !== id);
    });

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /restore all/i }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Restore all" }));

    const running = await screen.findByRole("button", { name: /restoring/i });
    expect(running).toBeDisabled();
    expect(screen.getByRole("button", { name: /empty trash/i })).toBeDisabled();

    releaseRestore();

    await waitFor(() => expect(toastMock.success).toHaveBeenCalledWith("Restored 3 items"));
    expect(filesApiMock.restore).toHaveBeenCalledTimes(3);
    expect(filesApiMock.restore.mock.calls.map(([id]) => id).sort()).toEqual(["f1", "f2", "f3"]);
    expect(filesApiMock.permanentDelete).not.toHaveBeenCalled();
    expect(await screen.findByText("Trash is empty")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /restore all/i })).not.toBeInTheDocument();
  });

  it("hides Restore all when the trash is empty", async () => {
    trashed = [];
    renderPage();
    expect(await screen.findByText("Trash is empty")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /restore all/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /empty trash/i })).not.toBeInTheDocument();
  });

  it("still empties the trash via Empty Trash without restoring anything", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /empty trash/i }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Delete all permanently" })
    );

    await waitFor(() => expect(toastMock.success).toHaveBeenCalledWith("Trash emptied"));
    expect(filesApiMock.permanentDelete).toHaveBeenCalledTimes(3);
    expect(filesApiMock.restore).not.toHaveBeenCalled();
    expect(await screen.findByText("Trash is empty")).toBeInTheDocument();
  });
});
