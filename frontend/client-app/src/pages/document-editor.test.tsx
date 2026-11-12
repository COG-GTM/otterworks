import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import DocumentEditorPage from "./document-editor";

vi.mock("@/components/layout/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/editor/collaborative-editor", () => ({
  CollaborativeEditor: () => <div data-testid="editor" />,
}));
vi.mock("@/lib/api", () => ({
  documentsApi: {
    get: vi.fn().mockResolvedValue({
      id: "doc-1",
      title: "Quarterly plan",
      content: "",
      ownerId: "u1",
      ownerName: "Otter",
      parentId: null,
      sharedWith: [],
      collaborators: [],
      tags: [],
      wordCount: 0,
      createdAt: "2026-01-01T00:00:00Z",
      updatedAt: "2026-01-01T00:00:00Z",
    }),
    update: vi.fn(),
    delete: vi.fn(),
  },
}));

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

describe("Document title rename", () => {
  it("exposes the title as a keyboard-focusable button that opens the rename input", async () => {
    renderPage();
    const heading = await screen.findByRole("heading", { level: 1, name: "Quarterly plan" });
    const trigger = screen.getByRole("button", { name: "Quarterly plan" });
    expect(heading).toContainElement(trigger);
    expect(trigger).toHaveAttribute("type", "button");

    trigger.focus();
    expect(trigger).toHaveFocus();
    fireEvent.click(trigger);

    const input = screen.getByDisplayValue("Quarterly plan");
    expect(input.tagName).toBe("INPUT");
    expect(input).toHaveFocus();
  });
});
