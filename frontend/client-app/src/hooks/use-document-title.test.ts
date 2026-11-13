import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { formatDocumentTitle, useDocumentTitle } from "./use-document-title";

describe("formatDocumentTitle", () => {
  it("appends the app name to the page name", () => {
    expect(formatDocumentTitle("Trash")).toBe("Trash \u00b7 OtterWorks");
    expect(formatDocumentTitle("Q3 roadmap.docx")).toBe("Q3 roadmap.docx \u00b7 OtterWorks");
  });

  it("falls back to the app name when the page name is empty", () => {
    expect(formatDocumentTitle()).toBe("OtterWorks");
    expect(formatDocumentTitle(null)).toBe("OtterWorks");
    expect(formatDocumentTitle("   ")).toBe("OtterWorks");
  });

  it("trims surrounding whitespace", () => {
    expect(formatDocumentTitle("  Starred  ")).toBe("Starred \u00b7 OtterWorks");
  });
});

describe("useDocumentTitle", () => {
  afterEach(() => {
    document.title = "";
  });

  it("sets the tab title for the page", () => {
    renderHook(() => useDocumentTitle("Settings"));
    expect(document.title).toBe("Settings \u00b7 OtterWorks");
  });

  it("updates the tab title when the page name changes", () => {
    const { rerender } = renderHook(({ page }) => useDocumentTitle(page), {
      initialProps: { page: undefined as string | undefined },
    });
    expect(document.title).toBe("OtterWorks");

    rerender({ page: "Q3 roadmap.docx" });
    expect(document.title).toBe("Q3 roadmap.docx \u00b7 OtterWorks");
  });

  it("restores the previous tab title on unmount", () => {
    document.title = "OtterWorks";
    const { unmount } = renderHook(() => useDocumentTitle("Trash"));
    expect(document.title).toBe("Trash \u00b7 OtterWorks");

    unmount();
    expect(document.title).toBe("OtterWorks");
  });
});
