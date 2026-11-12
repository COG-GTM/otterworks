import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FileItem } from "@/types";
import { filesApi } from "@/lib/api";
import { useUIStore } from "@/stores/ui-store";
import SharedPage from "./shared";

vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/api", () => ({
  filesApi: { getShared: vi.fn(), getDownloadUrl: vi.fn() },
  starredApi: { isStarred: vi.fn().mockResolvedValue(false) },
}));

function sharedFile(id: string, name: string): FileItem {
  return {
    id,
    name,
    mimeType: "text/plain",
    size: 10,
    parentId: null,
    ownerId: "owner",
    ownerName: "Owner",
    isFolder: false,
    path: `/${name}`,
    sharedWith: [],
    tags: [],
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    versions: [],
  };
}

function renderShared() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SharedPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SharedPage", () => {
  beforeEach(() => {
    vi.mocked(filesApi.getShared).mockReset();
    useUIStore.setState({ viewMode: "grid" });
  });

  it("shows the loader while shared files are loading", () => {
    vi.mocked(filesApi.getShared).mockReturnValue(new Promise(() => {}));
    const { container } = renderShared();
    expect(container.querySelector(".animate-spin")).not.toBeNull();
    expect(screen.queryByText("Nothing shared with you yet")).not.toBeInTheDocument();
  });

  it("shows the empty state when nothing is shared", async () => {
    vi.mocked(filesApi.getShared).mockResolvedValue({ data: [] } as never);
    renderShared();
    expect(await screen.findByText("Nothing shared with you yet")).toBeInTheDocument();
  });

  it("lists deduplicated shared files and switches layout", async () => {
    vi.mocked(filesApi.getShared).mockResolvedValue({
      data: [sharedFile("f1", "report.txt"), sharedFile("f1", "report.txt"), sharedFile("f2", "notes.txt")],
    } as never);
    renderShared();
    expect(await screen.findAllByText("report.txt")).toHaveLength(1);
    expect(screen.getByText("notes.txt")).toBeInTheDocument();
    expect(screen.queryByText("Nothing shared with you yet")).not.toBeInTheDocument();
    const list = screen.getByText("notes.txt").closest(".grid");
    expect(list).not.toBeNull();
    fireEvent.click(screen.getAllByRole("button")[1]);
    expect(useUIStore.getState().viewMode).toBe("list");
    expect(screen.getByText("notes.txt").closest(".space-y-1")).not.toBeNull();
  });
});
