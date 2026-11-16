import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HighlightedText } from "./highlighted-text";

function marks(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll("mark")).map((m) => m.textContent ?? "");
}

describe("HighlightedText", () => {
  it("highlights a case-insensitive match", () => {
    const { container } = render(<HighlightedText text="Quarterly Report.pdf" query="report" />);
    expect(marks(container)).toEqual(["Report"]);
    expect(container).toHaveTextContent("Quarterly Report.pdf");
  });

  it("highlights every occurrence", () => {
    const { container } = render(<HighlightedText text="Otter notes about otters" query="OTTER" />);
    expect(marks(container)).toEqual(["Otter", "otter"]);
    expect(container).toHaveTextContent("Otter notes about otters");
  });

  it("treats special characters in the query as plain text", () => {
    const { container } = render(
      <HighlightedText text="Budget (v2) [final].xlsx and budget v2" query="(v2) [" />
    );
    expect(marks(container)).toEqual(["(v2) ["]);
    expect(container).toHaveTextContent("Budget (v2) [final].xlsx and budget v2");

    const dot = render(<HighlightedText text="a.b axb a.b" query="." />);
    expect(marks(dot.container)).toEqual([".", "."]);
  });

  it("does not highlight when the query is empty", () => {
    const { container } = render(<HighlightedText text="Quarterly Report.pdf" query="" />);
    expect(container.querySelectorAll("mark")).toHaveLength(0);
    expect(container).toHaveTextContent("Quarterly Report.pdf");
  });

  it("does not highlight when nothing matches", () => {
    const { container } = render(<HighlightedText text="Quarterly Report.pdf" query="zzz" />);
    expect(container.querySelectorAll("mark")).toHaveLength(0);
  });
});
