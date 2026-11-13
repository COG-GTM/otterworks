import type { ReactNode } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { Document, FileItem } from "@/types";

const mocks = vi.hoisted(() => ({
  getRecentFiles: vi.fn(),
  getRecentDocs: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  filesApi: { getRecent: mocks.getRecentFiles, getDownloadUrl: vi.fn() },
  documentsApi: { getRecent: mocks.getRecentDocs },
}));
vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/files/file-card", () => ({
  FileCard: ({ file }: { file: FileItem }) => <div data-testid="file-card">{file.name}</div>,
}));
vi.mock("@/components/documents/document-card", () => ({
  DocumentCard: ({ document }: { document: Document }) => (
    <div data-testid="document-card">{document.title}</div>
  ),
}));

import RecentPage from "./recent";

const now = new Date();
const today = now.toISOString();
const longAgo = new Date(now.getFullYear() - 1, 0, 1).toISOString();

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RecentPage />
    </QueryClientProvider>
  );
}

function filterButton(name: string) {
  return within(screen.getByRole("group", { name: "Filter recent items" })).getByRole(
    "button",
    { name }
  );
}

describe("Recent page filter", () => {
  beforeEach(() => {
    mocks.getRecentFiles.mockResolvedValue([
      { id: "f1", name: "report.pdf", updatedAt: today },
      { id: "f2", name: "old.zip", updatedAt: longAgo },
    ]);
    mocks.getRecentDocs.mockResolvedValue([
      { id: "d1", title: "Roadmap", updatedAt: today },
    ]);
  });

  it("defaults to All and shows files and documents with the total count", async () => {
    renderPage();
    expect(await screen.findByText("report.pdf")).toBeInTheDocument();
    expect(filterButton("All")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Roadmap")).toBeInTheDocument();
    expect(screen.getByTestId("recent-count")).toHaveTextContent("3 items");
    expect(screen.getByText("Today")).toBeInTheDocument();
    expect(screen.getByText("Earlier")).toBeInTheDocument();
  });

  it("filters to documents, updates the count and hides empty groups", async () => {
    renderPage();
    await screen.findByText("report.pdf");
    fireEvent.click(filterButton("Documents"));

    expect(filterButton("Documents")).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByTestId("file-card")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("document-card")).toHaveLength(1);
    expect(screen.getByTestId("recent-count")).toHaveTextContent("1 item");
    expect(screen.getByText("Today")).toBeInTheDocument();
    expect(screen.queryByText("Earlier")).not.toBeInTheDocument();
  });

  it("filters to files", async () => {
    renderPage();
    await screen.findByText("report.pdf");
    fireEvent.click(filterButton("Files"));

    expect(screen.getAllByTestId("file-card")).toHaveLength(2);
    expect(screen.queryByTestId("document-card")).not.toBeInTheDocument();
    expect(screen.getByTestId("recent-count")).toHaveTextContent("2 items");
  });

  it("shows a filter-specific empty state when nothing matches", async () => {
    mocks.getRecentDocs.mockResolvedValue([]);
    renderPage();
    await screen.findByText("report.pdf");
    fireEvent.click(filterButton("Documents"));

    expect(screen.getByText("No recent documents")).toBeInTheDocument();
    expect(screen.getByTestId("recent-count")).toHaveTextContent("0 items");
  });

  it("shows 'No recent files' when there are no files", async () => {
    mocks.getRecentFiles.mockResolvedValue([]);
    renderPage();
    await screen.findByText("Roadmap");
    fireEvent.click(filterButton("Files"));

    expect(screen.getByText("No recent files")).toBeInTheDocument();
  });
});
