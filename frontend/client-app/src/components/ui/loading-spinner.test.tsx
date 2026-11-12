import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LoadingSpinner, PageLoader } from "./loading-spinner";

describe("LoadingSpinner", () => {
  it("renders a native <output> live region labelled Loading", () => {
    render(<LoadingSpinner />);
    const spinner = screen.getByRole("status", { name: "Loading" });
    expect(spinner.tagName).toBe("OUTPUT");
    expect(spinner).not.toHaveAttribute("role");
  });

  it("keeps block layout, size and custom classes", () => {
    render(<LoadingSpinner size="sm" className="extra" />);
    const spinner = screen.getByRole("status", { name: "Loading" });
    expect(spinner).toHaveClass("block", "animate-spin", "w-4", "h-4", "extra");
  });

  it("PageLoader exposes a single large spinner", () => {
    render(<PageLoader />);
    const spinners = screen.getAllByRole("status", { name: "Loading" });
    expect(spinners).toHaveLength(1);
    expect(spinners[0]).toHaveClass("w-12", "h-12");
  });
});
