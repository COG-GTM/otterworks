import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  DashboardSkeleton,
  FileGridSkeleton,
  FileListSkeleton,
} from "./skeleton";

describe("skeleton placeholders", () => {
  const consoleError = vi.spyOn(console, "error");

  afterEach(() => consoleError.mockClear());

  it("renders the requested number of file cards", () => {
    const { container } = render(<FileGridSkeleton count={5} />);
    expect(container.firstElementChild?.children).toHaveLength(5);
  });

  it("renders the requested number of file rows", () => {
    const { container } = render(<FileListSkeleton count={3} />);
    expect(container.firstElementChild?.children).toHaveLength(3);
  });

  it("renders four stat cards and four rows on the dashboard", () => {
    const { container } = render(<DashboardSkeleton />);
    const [stats, content] = Array.from(container.firstElementChild!.children);
    expect(stats.children).toHaveLength(4);
    expect(content.querySelector(".space-y-3")?.children).toHaveLength(4);
  });

  it("renders all placeholders without React key warnings", () => {
    render(
      <>
        <FileGridSkeleton />
        <FileListSkeleton />
        <DashboardSkeleton />
      </>
    );
    expect(consoleError).not.toHaveBeenCalled();
  });
});
