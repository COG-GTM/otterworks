import { format } from "date-fns";
import { formatFileSize } from "@/lib/utils";
import type { FileItem } from "@/types";

export const FILES_CSV_HEADERS = ["Name", "Type", "Size", "Last modified", "Owner"] as const;

type CsvItem = Pick<FileItem, "name" | "isFolder" | "size" | "updatedAt" | "ownerName" | "ownerId">;

// RFC 4180: quote a field when it contains a comma, double quote, CR or LF,
// doubling any embedded double quotes.
export function escapeCsvValue(value: string): string {
  if (/[",\r\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function formatLastModified(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? (value ?? "") : date.toISOString();
}

export function fileItemToCsvRow(item: CsvItem): string[] {
  return [
    item.name,
    item.isFolder ? "Folder" : "File",
    item.isFolder ? "" : formatFileSize(item.size),
    formatLastModified(item.updatedAt),
    item.ownerName || item.ownerId || "",
  ];
}

export function buildFilesCsv(items: readonly CsvItem[]): string {
  const rows = [Array.from(FILES_CSV_HEADERS), ...items.map(fileItemToCsvRow)];
  return rows.map((row) => row.map(escapeCsvValue).join(",")).join("\r\n") + "\r\n";
}

export function filesCsvFilename(date: Date = new Date()): string {
  return `otterworks-files-${format(date, "yyyy-MM-dd")}.csv`;
}

export function downloadCsv(csv: string, filename: string): void {
  // Leading BOM so spreadsheet apps detect UTF-8 for non-ASCII names.
  const blob = new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
