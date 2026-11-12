import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";

const ids = { fileIds: [] as string[], folderIds: [] as string[], documentIds: [] as string[] };
vi.mock("@/lib/api", () => ({
  starredApi: { getStarredIds: () => ids },
  filesApi: {
    get: async (id: string) => ({ id, name: `file-${id}` }),
    getFolder: async (id: string) => ({ id, name: `folder-${id}` }),
  },
  documentsApi: { get: async (id: string) => ({ id, title: `doc-${id}` }) },
}));
vi.mock("@/stores/auth-store", () => ({ useAuthStore: () => ({ user: { id: "u1" }, isLoading: false }) }));
vi.mock("@/components/layout/app-shell", () => ({ AppShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("@/components/layout/breadcrumb", () => ({ Breadcrumb: () => null }));
vi.mock("@/components/files/file-card", () => ({ FileCard: ({ file, view }: { file: { name: string }; view: string }) => <div data-testid="file">{file.name}:{view}</div> }));
vi.mock("@/components/documents/document-card", () => ({ DocumentCard: ({ document, view }: { document: { title: string }; view: string }) => <div data-testid="doc">{document.title}:{view}</div> }));

import StarredPage from "./starred";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><StarredPage /></QueryClientProvider>);
}

describe("Starred page", () => {
  beforeEach(() => { ids.fileIds = []; ids.folderIds = []; ids.documentIds = []; });
  it("empty state", async () => {
    renderPage();
    expect(await screen.findByText("No starred items")).toBeInTheDocument();
    expect(screen.queryByText("Files")).toBeNull();
  });
  it("loading then populated sections + view toggle", async () => {
    ids.fileIds = ["f1"]; ids.folderIds = ["d1"]; ids.documentIds = ["x1"];
    const { container } = renderPage();
    expect(container.querySelector(".animate-spin")).not.toBeNull();
    expect(await screen.findByText("file-f1:grid")).toBeInTheDocument();
    expect(screen.getByText("folder-d1:grid")).toBeInTheDocument();
    expect(screen.getByText("doc-x1:grid")).toBeInTheDocument();
    expect(screen.getByText("Files")).toBeInTheDocument();
    expect(screen.getByText("Documents")).toBeInTheDocument();
    expect(screen.queryByText("No starred items")).toBeNull();
    fireEvent.click(container.querySelectorAll("button")[1]);
    expect(await screen.findByText("file-f1:list")).toBeInTheDocument();
    expect(screen.getByText("doc-x1:list")).toBeInTheDocument();
  });
  it("only documents -> no Files section", async () => {
    ids.documentIds = ["x2"];
    renderPage();
    expect(await screen.findByText(/doc-x2/)).toBeInTheDocument();
    expect(screen.queryByText("Files")).toBeNull();
  });
});
