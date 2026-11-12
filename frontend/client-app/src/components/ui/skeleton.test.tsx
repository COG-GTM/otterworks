import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  DashboardSkeleton,
  FileGridSkeleton,
  FileListSkeleton,
} from "./skeleton";

describe("Skeleton placeholders", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  function captureKeyWarnings() {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    return () =>
      spy.mock.calls.filter((args) => args.map(String).join(" ").includes("key"));
  }

  it("renders the requested number of file cards without key warnings", () => {
    const keyWarnings = captureKeyWarnings();
    const { container, rerender } = render(<FileGridSkeleton count={3} />);
    expect(container.firstElementChild?.children).toHaveLength(3);
    rerender(<FileGridSkeleton count={5} />);
    expect(container.firstElementChild?.children).toHaveLength(5);
    expect(keyWarnings()).toEqual([]);
  });

  it("renders the requested number of list rows without key warnings", () => {
    const keyWarnings = captureKeyWarnings();
    const { container } = render(<FileListSkeleton count={4} />);
    expect(container.firstElementChild?.children).toHaveLength(4);
    expect(keyWarnings()).toEqual([]);
  });

  it("renders dashboard stat and recent-item placeholders without key warnings", () => {
    const keyWarnings = captureKeyWarnings();
    const { container } = render(<DashboardSkeleton />);
    const [stats, content] = Array.from(container.firstElementChild?.children ?? []);
    expect(stats.children).toHaveLength(4);
    expect(content.querySelector(".space-y-3")?.children).toHaveLength(4);
    expect(keyWarnings()).toEqual([]);
  });
});
