export type FileTypeCategory = "image" | "pdf" | "document" | "other";

export type FileTypeFilter = "all" | FileTypeCategory;

export const FILE_TYPE_FILTERS: ReadonlyArray<{ value: FileTypeFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "image", label: "Images" },
  { value: "pdf", label: "PDFs" },
  { value: "document", label: "Documents" },
  { value: "other", label: "Other" },
];

const DOCUMENT_MIME_TYPES = new Set([
  "application/msword",
  "application/rtf",
  "application/vnd.ms-excel",
  "application/vnd.ms-powerpoint",
  "application/vnd.apple.pages",
  "application/vnd.apple.numbers",
  "application/vnd.apple.keynote",
]);

const DOCUMENT_MIME_PREFIXES = [
  "text/",
  "application/vnd.openxmlformats-officedocument.",
  "application/vnd.oasis.opendocument.",
];

export function getFileTypeCategory(mimeType: string | null | undefined): FileTypeCategory {
  const type = (mimeType ?? "").split(";")[0].trim().toLowerCase();
  if (!type) return "other";
  if (type.startsWith("image/")) return "image";
  if (type === "application/pdf") return "pdf";
  if (DOCUMENT_MIME_TYPES.has(type)) return "document";
  if (DOCUMENT_MIME_PREFIXES.some((prefix) => type.startsWith(prefix))) return "document";
  return "other";
}

export function matchesFileTypeFilter(
  mimeType: string | null | undefined,
  filter: FileTypeFilter,
): boolean {
  return filter === "all" || getFileTypeCategory(mimeType) === filter;
}
