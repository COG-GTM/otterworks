import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Breadcrumb, type BreadcrumbItem } from "./breadcrumb";

function renderTrail(items: BreadcrumbItem[]) {
  return render(
    <MemoryRouter>
      <Breadcrumb items={items} />
    </MemoryRouter>
  );
}

describe("Breadcrumb", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders linked and current items", () => {
    renderTrail([{ label: "Files", href: "/files" }, { label: "report.pdf" }]);

    expect(screen.getByRole("link", { name: "Files" })).toHaveAttribute("href", "/files");
    expect(screen.getByText("report.pdf").tagName).toBe("SPAN");
    expect(screen.queryByRole("link", { name: "report.pdf" })).toBeNull();
  });

  it("keeps each item's DOM node when the trail changes", () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const { rerender } = renderTrail([
      { label: "Files", href: "/files" },
      { label: "report.pdf" },
    ]);
    const filesItem = screen.getByRole("link", { name: "Files" }).parentElement;

    rerender(
      <MemoryRouter>
        <Breadcrumb
          items={[
            { label: "Shared", href: "/shared" },
            { label: "Files", href: "/files" },
            { label: "report.pdf" },
          ]}
        />
      </MemoryRouter>
    );

    expect(screen.getByRole("link", { name: "Files" }).parentElement).toBe(filesItem);
    expect(errors).not.toHaveBeenCalledWith(expect.stringContaining("key"), expect.anything());
  });
});
