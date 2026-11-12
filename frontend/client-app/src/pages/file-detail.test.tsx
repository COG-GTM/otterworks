import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FileItem } from "@/types";

const api = vi.hoisted(() => ({
  filesApi: {
    get: vi.fn(),
    getDownloadUrl: vi.fn(),
    delete: vi.fn(),
    share: vi.fn(),
    updateSharePermission: vi.fn(),
    removeShare: vi.fn(),
  },
  authApi: { lookupUserById: vi.fn() },
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));

vi.mock("@/lib/api", () => api);
vi.mock("react-hot-toast", () => ({ default: toast }));
vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

import FileDetailPage from "./file-detail";

const FILE: FileItem = {
  id: "file-1",
  name: "report.bin",
  mimeType: "application/octet-stream",
  size: 2048,
  parentId: null,
  ownerId: "owner-1",
  ownerName: "Olive Otter",
  isFolder: false,
  path: "/docs/report.bin",
  sharedWith: [],
  tags: [],
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-02T00:00:00Z",
  versions: [],
};

function renderPage(fileId = FILE.id) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/files/${fileId}`]}>
        <Routes>
          <Route path="/files/:id" element={<FileDetailPage />} />
          <Route path="/files" element={<p>Files list</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("FileDetailPage", () => {
  beforeEach(() => {
    api.filesApi.getDownloadUrl.mockResolvedValue("https://s3.example/report.bin");
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("shows not found when the file does not load", async () => {
    api.filesApi.get.mockResolvedValue(undefined);
    renderPage("missing");
    expect(await screen.findByText("File not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to files" })).toHaveAttribute("href", "/files");
  });

  it("renders details, empty sharing, no tags or versions, and the fallback preview", async () => {
    api.filesApi.get.mockResolvedValue(FILE);
    renderPage();

    expect(await screen.findByRole("heading", { name: "report.bin" })).toBeInTheDocument();
    expect(screen.getByText("Olive Otter")).toBeInTheDocument();
    expect(screen.getByText("/docs/report.bin")).toBeInTheDocument();
    expect(screen.getByText("Not shared with anyone")).toBeInTheDocument();
    expect(screen.queryByText("Tags")).not.toBeInTheDocument();
    expect(screen.queryByText(/^Versions/)).not.toBeInTheDocument();
    expect(await screen.findByText("Preview not available for this file type")).toBeInTheDocument();
  });

  it("renders versions, tags and shared users with resolved names", async () => {
    api.filesApi.get.mockResolvedValue({
      ...FILE,
      ownerName: "",
      tags: ["q1", "finance"],
      versions: [
        { id: "v1", fileId: FILE.id, versionNumber: 1, size: 1024, uploadedBy: "olive", createdAt: FILE.createdAt, downloadUrl: "/v1" },
      ],
      sharedWith: [
        { userId: "user-resolved", name: "", email: "", permission: "edit" },
        { userId: "user-unresolved-123", name: "", email: "", permission: "view" },
      ],
    });
    api.authApi.lookupUserById.mockImplementation(async (id: string) => {
      if (id === "user-resolved") return { id, email: "sam@example.com", displayName: "Sam Seal" };
      throw new Error("not found");
    });
    renderPage();

    expect(await screen.findByText("Versions (1)")).toBeInTheDocument();
    expect(screen.getByText("Version 1")).toBeInTheDocument();
    expect(screen.getByText("q1")).toBeInTheDocument();
    expect(screen.getByText("finance")).toBeInTheDocument();
    expect(screen.getByText("You")).toBeInTheDocument();
    expect(await screen.findByText("Sam Seal")).toBeInTheDocument();
    expect(screen.getByText("sam@example.com · edit")).toBeInTheDocument();
    expect(screen.getByText("user-unr")).toBeInTheDocument();
    expect(screen.getByText("view")).toBeInTheDocument();
  });

  it("previews JSON files as text", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"ok":true}', { status: 200 })));
    api.filesApi.get.mockResolvedValue({ ...FILE, name: "data.json", mimeType: "application/json" });
    renderPage();

    expect(await screen.findByText('{"ok":true}')).toBeInTheDocument();
  });

  it("downloads the file and reports success", async () => {
    api.filesApi.get.mockResolvedValue(FILE);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Download" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Downloading report.bin"));
    expect(click).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Download" })).toBeEnabled();
  });

  it("reports a failed download", async () => {
    api.filesApi.get.mockResolvedValue(FILE);
    renderPage();
    await screen.findByRole("button", { name: "Download" });
    api.filesApi.getDownloadUrl.mockRejectedValueOnce(new Error("boom"));

    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Download failed. Please try again."));
  });

  it("moves the file to trash and returns to the files list", async () => {
    api.filesApi.get.mockResolvedValue(FILE);
    api.filesApi.delete.mockResolvedValue(undefined);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(await screen.findByText("Files list")).toBeInTheDocument();
    expect(api.filesApi.delete).toHaveBeenCalledWith(FILE.id);
    expect(toast.success).toHaveBeenCalledWith("File moved to trash");
  });
});
