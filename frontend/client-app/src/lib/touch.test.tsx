import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { actionRevealClass, isInteractiveTarget, tapTargetClass, COARSE_POINTER_QUERY } from "./touch";
import { FileCard } from "@/components/files/file-card";
import type { FileItem } from "@/types";

function mockMatchMedia(coarse: boolean) {
  const listeners = new Set<(e: MediaQueryListEvent) => void>();
  const impl = vi.fn((query: string) => ({
    media: query,
    matches: query === COARSE_POINTER_QUERY ? coarse : false,
    onchange: null,
    addEventListener: (_: string, cb: (e: MediaQueryListEvent) => void) => listeners.add(cb),
    removeEventListener: (_: string, cb: (e: MediaQueryListEvent) => void) => listeners.delete(cb),
    addListener: (cb: (e: MediaQueryListEvent) => void) => listeners.add(cb),
    removeListener: (cb: (e: MediaQueryListEvent) => void) => listeners.delete(cb),
    dispatchEvent: () => false,
  }));
  vi.stubGlobal("matchMedia", impl);
  return impl;
}

const file: FileItem = {
  id: "file-1",
  name: "report.pdf",
  mimeType: "application/pdf",
  size: 1024,
  isFolder: false,
  ownerId: "user-1",
  ownerName: "Otter",
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
  sharedWith: [],
} as unknown as FileItem;

function renderCard(props: Partial<React.ComponentProps<typeof FileCard>> = {}) {
  return render(
    <MemoryRouter>
      <FileCard file={file} view="list" {...props} />
    </MemoryRouter>
  );
}

describe("coarse-pointer branch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps hover/focus reveal classes on fine pointers", () => {
    expect(actionRevealClass(false)).toContain("opacity-0");
    expect(actionRevealClass(false)).toContain("group-hover:opacity-100");
    expect(actionRevealClass(false)).toContain("group-focus-within:opacity-100");
    expect(tapTargetClass(false)).toBe("");
  });

  it("drops the hover gate and enlarges tap targets on coarse pointers", () => {
    expect(actionRevealClass(true)).toBe("opacity-100");
    expect(tapTargetClass(true)).toContain("min-h-[44px]");
    expect(tapTargetClass(true)).toContain("min-w-[44px]");
  });

  it("hides file card actions behind hover on a desktop pointer", () => {
    mockMatchMedia(false);
    renderCard();
    const actions = screen.getByLabelText("File actions");
    expect(actions.className).toContain("opacity-0");
    expect(actions.className).not.toContain("min-h-[44px]");
  });

  it("shows file card actions with 44px targets on a touch device", () => {
    const impl = mockMatchMedia(true);
    renderCard();
    expect(impl).toHaveBeenCalledWith(COARSE_POINTER_QUERY);
    const actions = screen.getByLabelText("File actions");
    expect(actions.className).not.toContain("opacity-0");
    expect(actions.className).toContain("min-h-[44px]");
    const star = screen.getByLabelText("Star");
    expect(star.className).not.toContain("opacity-0");
    expect(star.className).toContain("min-w-[44px]");
  });

  it("lets card controls keep working while a touch selection is active", () => {
    mockMatchMedia(true);
    const onSelect = vi.fn();
    renderCard({ selectionActive: true, onSelect });
    fireEvent.click(screen.getByLabelText("File actions"));
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByText("Download")).toBeTruthy();
  });

  it("treats only real controls as interactive targets", () => {
    const { container } = render(
      <div>
        <button type="button">
          <span data-testid="inside-button" />
        </button>
        <p data-testid="plain" />
      </div>
    );
    expect(isInteractiveTarget(screen.getByTestId("inside-button"))).toBe(true);
    expect(isInteractiveTarget(screen.getByTestId("plain"))).toBe(false);
    expect(isInteractiveTarget(null)).toBe(false);
    expect(container).toBeTruthy();
  });
});
