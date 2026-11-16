import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StorageUsageBar } from "./storage-usage-bar";

function barFill() {
  return screen.getByRole("progressbar").firstElementChild as HTMLElement;
}

describe("StorageUsageBar", () => {
  it("uses the normal color and no warning below 80%", () => {
    render(<StorageUsageBar used={79} total={100} />);
    expect(barFill()).toHaveClass("bg-otter-600");
    expect(screen.queryByText(/running out of space/i)).not.toBeInTheDocument();
  });

  it("turns amber and warns with the percent used from 80%", () => {
    render(<StorageUsageBar used={85} total={100} />);
    expect(barFill()).toHaveClass("bg-amber-500");
    expect(screen.getByRole("status")).toHaveTextContent("You're running out of space (85% used)");
  });

  it("turns red from 95%", () => {
    render(<StorageUsageBar used={97} total={100} />);
    expect(barFill()).toHaveClass("bg-red-600");
    expect(screen.getByRole("status")).toHaveTextContent("97% used");
  });
});
