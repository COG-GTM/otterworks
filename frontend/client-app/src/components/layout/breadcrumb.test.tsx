import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Breadcrumb, type BreadcrumbItem } from "./breadcrumb";

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

function renderBreadcrumb(items: BreadcrumbItem[]) {
  return render(
    <MemoryRouter initialEntries={["/files?folder=current"]}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              <Breadcrumb items={items} />
              <LocationProbe />
            </>
          }
        />
      </Routes>
    </MemoryRouter>
  );
}

const folder = (id: string, label: string): BreadcrumbItem => ({
  label,
  href: `/files?folder=${id}`,
});

describe("Breadcrumb", () => {
  it("renders every item without collapsing when there are 3 items", () => {
    renderBreadcrumb([
      { label: "Files", href: "/files" },
      folder("a", "Projects"),
      { label: "Reports" },
    ]);

    const nav = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(nav).getByRole("link", { name: "Files" })).toHaveAttribute("href", "/files");
    expect(within(nav).getByRole("link", { name: "Projects" })).toHaveAttribute(
      "href",
      "/files?folder=a"
    );
    expect(within(nav).getByText("Reports")).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("button", { name: "Show hidden folders" })).not.toBeInTheDocument();
  });

  it("collapses 6 items to first, ellipsis and last 2, and the menu navigates", () => {
    renderBreadcrumb([
      { label: "Files", href: "/files" },
      folder("a", "Alpha"),
      folder("b", "Bravo"),
      folder("c", "Charlie"),
      folder("d", "Delta"),
      { label: "Echo" },
    ]);

    const nav = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(nav).getByRole("link", { name: "Files" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Delta" })).toBeInTheDocument();
    expect(within(nav).getByText("Echo")).toBeInTheDocument();
    for (const hidden of ["Alpha", "Bravo", "Charlie"]) {
      expect(within(nav).queryByText(hidden)).not.toBeInTheDocument();
    }

    const toggle = within(nav).getByRole("button", { name: "Show hidden folders" });
    expect(toggle).toHaveTextContent("\u2026");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const menu = screen.getByRole("menu", { name: "Hidden folders" });
    const entries = within(menu).getAllByRole("menuitem");
    expect(entries.map((entry) => entry.textContent)).toEqual(["Alpha", "Bravo", "Charlie"]);

    fireEvent.click(within(menu).getByRole("menuitem", { name: "Bravo" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/files?folder=b");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("supports keyboard navigation and restores focus on Escape", () => {
    renderBreadcrumb([
      { label: "Files", href: "/files" },
      folder("a", "Alpha"),
      folder("b", "Bravo"),
      folder("c", "Charlie"),
      { label: "Delta" },
    ]);

    const toggle = screen.getByRole("button", { name: "Show hidden folders" });
    fireEvent.click(toggle);
    const menu = screen.getByRole("menu");
    const [alpha, bravo] = within(menu).getAllByRole("menuitem");
    expect(alpha).toHaveFocus();

    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(bravo).toHaveFocus();
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(alpha).toHaveFocus();
    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(bravo).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(toggle).toHaveFocus();
  });

  it("truncates long names and exposes the full name as a title tooltip", () => {
    const longName = "Quarterly financial reports for the entire northern region 2026";
    renderBreadcrumb([
      { label: "Files", href: "/files" },
      folder("a", longName),
      { label: longName },
    ]);

    const link = screen.getByRole("link", { name: longName });
    expect(link).toHaveAttribute("title", longName);
    expect(link).toHaveClass("truncate");
    const current = screen.getByText(longName, { selector: "span" });
    expect(current).toHaveAttribute("title", longName);
    expect(current).toHaveClass("truncate");
  });
});
