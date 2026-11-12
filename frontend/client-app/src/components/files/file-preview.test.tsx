import { http, HttpResponse } from "msw";
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TextFilePreview } from "./file-preview";
import { billingServer } from "../../test-setup";

const PRESIGNED_URL = "http://storage.test/bucket/notes.txt";

function serveText(body: string) {
  billingServer.use(http.get(PRESIGNED_URL, () => new HttpResponse(body)));
}

function renderedRows() {
  return within(screen.getByRole("table")).getAllByRole("row");
}

describe("TextFilePreview", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders duplicate and blank lines with line numbers and no key warnings", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    serveText("same\nsame\n\nsame");

    render(<TextFilePreview presignedUrl={PRESIGNED_URL} fileName="notes.txt" />);

    expect(await screen.findByText("4 lines")).toBeInTheDocument();
    const rows = renderedRows();
    expect(rows.map((row) => row.textContent)).toEqual(["1same", "2same", "3\u00A0", "4same"]);
    expect(consoleError).not.toHaveBeenCalled();
  });

  it("re-renders rows for new content when the preview URL changes", async () => {
    serveText("alpha\nbeta");
    const { rerender } = render(
      <TextFilePreview presignedUrl={PRESIGNED_URL} fileName="notes.txt" />,
    );
    expect(await screen.findByText("2 lines")).toBeInTheDocument();

    const nextUrl = `${PRESIGNED_URL}?v=2`;
    billingServer.use(http.get(PRESIGNED_URL, () => new HttpResponse("gamma")));
    rerender(<TextFilePreview presignedUrl={nextUrl} fileName="notes.txt" />);

    expect(await screen.findByText("1 line")).toBeInTheDocument();
    expect(renderedRows().map((row) => row.textContent)).toEqual(["1gamma"]);
  });
});
