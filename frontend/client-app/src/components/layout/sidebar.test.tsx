import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { Sidebar } from "./sidebar";
import { useUIStore } from "@/stores/ui-store";

function renderSidebar() {
  return render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <Sidebar />
    </MemoryRouter>
  );
}

describe("Sidebar mobile overlay", () => {
  beforeEach(() => {
    useUIStore.setState({ sidebarOpen: true });
  });

  it("renders the overlay as a native, labelled button outside the tab order", () => {
    renderSidebar();
    const overlay = screen.getByRole("button", { name: "Close sidebar" });
    expect(overlay.tagName).toBe("BUTTON");
    expect(overlay).toHaveAttribute("type", "button");
    expect(overlay).toHaveAttribute("tabindex", "-1");
  });

  it("closes the sidebar when the overlay is clicked", () => {
    renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: "Close sidebar" }));
    expect(useUIStore.getState().sidebarOpen).toBe(false);
    expect(screen.queryByRole("button", { name: "Close sidebar" })).toBeNull();
  });

  it("does not render the overlay when the sidebar is collapsed", () => {
    useUIStore.setState({ sidebarOpen: false });
    renderSidebar();
    expect(screen.queryByRole("button", { name: "Close sidebar" })).toBeNull();
  });
});
