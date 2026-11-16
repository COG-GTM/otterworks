import { Fragment } from "react";
import { cn } from "@/lib/utils";

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

interface HighlightedTextProps {
  text: string;
  query: string;
  className?: string;
}

/**
 * Renders `text`, wrapping every case-insensitive occurrence of `query` in a
 * <mark>. The query is matched literally, never as a regular expression.
 */
export function HighlightedText({ text, query, className }: Readonly<HighlightedTextProps>) {
  if (!query) return <>{text}</>;

  const parts = text.split(new RegExp(`(${escapeRegExp(query)})`, "gi"));
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <mark
            key={i}
            className={cn("bg-yellow-100 text-inherit rounded-sm px-0.5 -mx-0.5", className)}
          >
            {part}
          </mark>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        )
      )}
    </>
  );
}
