import { useEffect } from "react";

export const APP_NAME = "OtterWorks";
const SEPARATOR = " \u00b7 ";

export function formatDocumentTitle(page?: string | null): string {
  const trimmed = page?.trim();
  return trimmed ? `${trimmed}${SEPARATOR}${APP_NAME}` : APP_NAME;
}

/**
 * Sets the browser tab title to "<page> · OtterWorks" while the calling
 * component is mounted, and restores the previous title on unmount.
 * An empty or missing page name falls back to plain "OtterWorks".
 */
export function useDocumentTitle(page?: string | null): void {
  const title = formatDocumentTitle(page);

  useEffect(() => {
    const previous = document.title;
    document.title = title;
    return () => {
      document.title = previous;
    };
  }, [title]);
}
