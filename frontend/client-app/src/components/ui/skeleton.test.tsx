import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DashboardSkeleton, FileGridSkeleton, FileListSkeleton } from "./skeleton";

describe("Skeleton placeholders", () => {
  const consoleError = vi.spyOn(console, "error");

  afterEach(() => {
    consoleError.mockClear();
  });

  function keyWarnings() {
    return consoleError.mock.calls.filter((args) =>
      String(args[0]).includes('unique "key" prop')
    );
  }

  it("renders the requested number of list rows with unique keys", () => {
    const { container } = render(<FileListSkeleton count={5} />);
    expect(container.firstElementChild?.children).toHaveLength(5);
    expect(keyWarnings()).toHaveLength(0);
  });

  it("renders the requested number of grid cards with unique keys", () => {
    const { container } = render(<FileGridSkeleton count={3} />);
    expect(container.firstElementChild?.children).toHaveLength(3);
    expect(keyWarnings()).toHaveLength(0);
  });

  it("keeps row count stable when the count changes", () => {
    const { container, rerender } = render(<FileListSkeleton count={2} />);
    rerender(<FileListSkeleton count={4} />);
    expect(container.firstElementChild?.children).toHaveLength(4);
    expect(keyWarnings()).toHaveLength(0);
  });

  it("renders four dashboard stat cards and four activity rows", () => {
    const { container } = render(<DashboardSkeleton />);
    const [stats, content] = Array.from(container.firstElementChild?.children ?? []);
    expect(stats.children).toHaveLength(4);
    expect(content.querySelectorAll(".space-y-3 > div")).toHaveLength(4);
    expect(keyWarnings()).toHaveLength(0);
  });
});
