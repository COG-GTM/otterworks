import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FileItem } from "@/types";

const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("react-hot-toast", () => ({ default: toastMock }));

vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

const filesApiMock = vi.hoisted(() => ({
  list: vi.fn(),
  listFolders: vi.fn(),
  getFolder: vi.fn(),
  delete: vi.fn(),
  deleteFolder: vi.fn(),
}));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, filesApi: { ...actual.filesApi, ...filesApiMock } };
});

import FilesPage from "./files";

function item(id: string, name: string, isFolder: boolean, updatedAt: string): FileItem {
  return {
    id,
    name,
    mimeType: isFolder ? "" : "text/plain",
    size: 10,
    parentId: null,
    ownerId: "u1",
    ownerName: "",
    isFolder,
    path: `/${name}`,
    sharedWith: [],
    tags: [],
    createdAt: updatedAt,
    updatedAt,
    versions: [],
  } as FileItem;
}

// Folders render before files; files are sorted newest-modified first.
const FOLDERS = [item("d1", "Folder One", true, "2026-01-01T00:00:00Z")];
const FILES = [
  item("f1", "a.txt", false, "2026-01-03T00:00:00Z"),
  item("f2", "b.txt", false, "2026-01-02T00:00:00Z"),
];

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/files"]}>
        <FilesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function selectAndDelete(indexes: number[]) {
  renderPage();
  await screen.findByText("a.txt");
  fireEvent.click(screen.getByRole("button", { name: "Select" }));
  const boxes = screen.getAllByRole("checkbox");
  for (const i of indexes) fireEvent.click(boxes[i]);
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
}

describe("FilesPage bulk delete", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    filesApiMock.list.mockResolvedValue({ data: FILES, total: 2, page: 1, pageSize: 50, hasMore: false });
    filesApiMock.listFolders.mockResolvedValue(FOLDERS);
    filesApiMock.delete.mockResolvedValue(undefined);
    filesApiMock.deleteFolder.mockResolvedValue(undefined);
  });

  it("trashes files, deletes folders and summarises both in one toast", async () => {
    await selectAndDelete([0, 1, 2]);
    await waitFor(() => expect(toastMock.success).toHaveBeenCalledWith("2 files moved to trash, 1 folder deleted"));
    expect(filesApiMock.delete.mock.calls.map((c) => c[0]).sort()).toEqual(["f1", "f2"]);
    expect(filesApiMock.deleteFolder).toHaveBeenCalledWith("d1");
    expect(toastMock.error).not.toHaveBeenCalled();
    expect(screen.queryByText(/selected$/)).not.toBeInTheDocument();
  });

  it("uses the singular form for a single file", async () => {
    await selectAndDelete([1]);
    await waitFor(() => expect(toastMock.success).toHaveBeenCalledWith("1 file moved to trash"));
    expect(filesApiMock.deleteFolder).not.toHaveBeenCalled();
  });

  it("reports failures separately without aborting the rest", async () => {
    filesApiMock.delete.mockRejectedValueOnce(new Error("boom"));
    filesApiMock.deleteFolder.mockRejectedValueOnce(new Error("boom"));
    await selectAndDelete([0, 1, 2]);
    await waitFor(() => expect(toastMock.error).toHaveBeenCalledWith("2 items failed to delete"));
    expect(toastMock.success).toHaveBeenCalledWith("1 file moved to trash");
    expect(filesApiMock.delete).toHaveBeenCalledTimes(2);
  });

  it("reports a single failure in the singular", async () => {
    filesApiMock.deleteFolder.mockRejectedValueOnce(new Error("boom"));
    await selectAndDelete([0]);
    await waitFor(() => expect(toastMock.error).toHaveBeenCalledWith("1 item failed to delete"));
    expect(toastMock.success).not.toHaveBeenCalled();
  });
});
