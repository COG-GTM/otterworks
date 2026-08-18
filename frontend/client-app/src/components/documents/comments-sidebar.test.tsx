// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import type { Comment } from "@/types";
import { CommentsSidebar } from "./comments-sidebar";
import { documentsApi } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  documentsApi: {
    listComments: vi.fn(),
    addComment: vi.fn(),
    resolveComment: vi.fn(),
    unresolveComment: vi.fn(),
  },
}));

const DOCUMENT_ID = "doc-1";

function makeComment(overrides: Partial<Comment> = {}): Comment {
  return {
    id: "c-1",
    documentId: DOCUMENT_ID,
    authorId: "user-1",
    content: "Otters need more fish",
    isResolved: false,
    resolvedBy: null,
    resolvedAt: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    ...overrides,
  };
}

function renderWithClient(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("CommentsSidebar", () => {
  beforeEach(() => {
    vi.mocked(documentsApi.listComments).mockReset();
    vi.mocked(documentsApi.resolveComment).mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("lists unresolved comments", async () => {
    vi.mocked(documentsApi.listComments).mockResolvedValue([
      makeComment({ id: "c-1", content: "Needs a citation" }),
      makeComment({ id: "c-2", content: "Fix the chart" }),
    ]);

    renderWithClient(<CommentsSidebar documentId={DOCUMENT_ID} />);

    expect(await screen.findByText("Needs a citation")).toBeTruthy();
    expect(screen.getByText("Fix the chart")).toBeTruthy();
    expect(screen.queryByText(/^Resolved \(/)).toBeNull();
  });

  it("resolves a comment when the resolve toggle is clicked", async () => {
    const comment = makeComment({ id: "c-9", content: "Tighten the intro" });
    vi.mocked(documentsApi.listComments).mockResolvedValue([comment]);
    vi.mocked(documentsApi.resolveComment).mockResolvedValue({
      ...comment,
      isResolved: true,
      resolvedBy: "user-1",
      resolvedAt: new Date().toISOString(),
    });

    renderWithClient(<CommentsSidebar documentId={DOCUMENT_ID} />);

    const resolveButton = await screen.findByLabelText("Resolve comment");
    fireEvent.click(resolveButton);

    await waitFor(() =>
      expect(documentsApi.resolveComment).toHaveBeenCalledWith(DOCUMENT_ID, "c-9")
    );
  });

  it("groups resolved comments into a dimmed collapsed section", async () => {
    vi.mocked(documentsApi.listComments).mockResolvedValue([
      makeComment({ id: "c-1", content: "Still open" }),
      makeComment({
        id: "c-2",
        content: "Already handled",
        isResolved: true,
        resolvedBy: "user-2",
        resolvedAt: new Date().toISOString(),
      }),
    ]);

    renderWithClient(<CommentsSidebar documentId={DOCUMENT_ID} />);

    const toggle = await screen.findByText("Resolved (1)");
    expect(screen.queryByText("Already handled")).toBeNull();

    fireEvent.click(toggle);

    const resolvedComment = await screen.findByText("Already handled");
    expect(screen.getByTestId("comment-c-2").className).toContain("opacity-50");
    expect(screen.getByTestId("comment-c-1").className).not.toContain("opacity-50");
    expect(resolvedComment).toBeTruthy();
    expect(screen.getByLabelText("Unresolve comment")).toBeTruthy();
  });
});
