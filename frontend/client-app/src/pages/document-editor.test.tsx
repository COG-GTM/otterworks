import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Document } from "@/types";

const { getDocument, updateDocument } = vi.hoisted(() => ({
  getDocument: vi.fn(),
  updateDocument: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  documentsApi: {
    get: getDocument,
    update: updateDocument,
    delete: vi.fn(),
    share: vi.fn(),
  },
}));
vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/editor/collaborative-editor", () => ({
  CollaborativeEditor: () => <div data-testid="editor" />,
}));

import DocumentEditorPage from "./document-editor";

const doc: Document = {
  id: "doc-1",
  title: "Quarterly plan",
  content: "<p>hello</p>",
  ownerId: "u1",
  ownerName: "Olive Otter",
  parentId: null,
  sharedWith: [],
  collaborators: [],
  tags: [],
  wordCount: 1,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/documents/doc-1"]}>
        <Routes>
          <Route path="/documents/:id" element={<DocumentEditorPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("Document editor title rename", () => {
  beforeEach(() => {
    getDocument.mockReset().mockResolvedValue(doc);
    updateDocument.mockReset().mockResolvedValue({ ...doc, title: "Q3 plan" });
  });

  it("exposes rename as a focusable button inside the heading, not a handler on the heading", async () => {
    renderPage();
    const heading = await screen.findByRole("heading", { level: 1, name: "Quarterly plan" });
    const rename = within(heading).getByRole("button", { name: "Quarterly plan" });

    expect(rename).toHaveAttribute("type", "button");
    expect(rename).toHaveAttribute("title", "Click to rename");
    expect(heading).not.toHaveAttribute("tabindex");
    expect(heading).not.toHaveAttribute("role");

    rename.focus();
    expect(rename).toHaveFocus();
  });

  it("renames the document after activating the title button", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Quarterly plan" }));

    const input = screen.getByDisplayValue("Quarterly plan");
    expect(input).toHaveFocus();
    fireEvent.change(input, { target: { value: "  Q3 plan  " } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(updateDocument).toHaveBeenCalledWith("doc-1", { title: "Q3 plan" }));
    expect(screen.queryByDisplayValue("Q3 plan")).not.toBeInTheDocument();
  });

  it("does not save when the title is unchanged", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Quarterly plan" }));
    fireEvent.blur(screen.getByDisplayValue("Quarterly plan"));

    expect(await screen.findByRole("button", { name: "Quarterly plan" })).toBeInTheDocument();
    expect(updateDocument).not.toHaveBeenCalled();
  });
});
