import { describe, it, expect, vi, afterEach } from "vitest";
import {
  buildFilesCsv,
  downloadCsv,
  escapeCsvValue,
  fileItemToCsvRow,
  filesCsvFilename,
} from "./files-csv";

const baseItem = {
  name: "report.pdf",
  isFolder: false,
  size: 2048,
  updatedAt: "2026-11-01T10:30:00.000Z",
  ownerName: "Olive Otter",
  ownerId: "user-1",
};

describe("escapeCsvValue", () => {
  it("leaves plain values untouched", () => {
    expect(escapeCsvValue("report.pdf")).toBe("report.pdf");
    expect(escapeCsvValue("")).toBe("");
  });

  it("quotes values containing commas", () => {
    expect(escapeCsvValue("Smith, Jane")).toBe('"Smith, Jane"');
  });

  it("quotes values containing double quotes and doubles them", () => {
    expect(escapeCsvValue('the "final" draft')).toBe('"the ""final"" draft"');
  });

  it("quotes values containing newlines or carriage returns", () => {
    expect(escapeCsvValue("line1\nline2")).toBe('"line1\nline2"');
    expect(escapeCsvValue("line1\r\nline2")).toBe('"line1\r\nline2"');
  });
});

describe("fileItemToCsvRow", () => {
  it("maps a file to Name, Type, Size, Last modified, Owner", () => {
    expect(fileItemToCsvRow(baseItem)).toEqual([
      "report.pdf",
      "File",
      "2 KB",
      "2026-11-01T10:30:00.000Z",
      "Olive Otter",
    ]);
  });

  it("leaves Size empty for folders", () => {
    const row = fileItemToCsvRow({ ...baseItem, name: "Invoices", isFolder: true, size: 0 });
    expect(row[1]).toBe("Folder");
    expect(row[2]).toBe("");
  });

  it("falls back to the owner id when no owner name is available", () => {
    expect(fileItemToCsvRow({ ...baseItem, ownerName: "" })[4]).toBe("user-1");
  });

  it("keeps an unparseable timestamp as-is", () => {
    expect(fileItemToCsvRow({ ...baseItem, updatedAt: "" })[3]).toBe("");
  });
});

describe("buildFilesCsv", () => {
  it("emits the header row even when there are no items", () => {
    expect(buildFilesCsv([])).toBe("Name,Type,Size,Last modified,Owner\r\n");
  });

  it("preserves the order of the items it is given", () => {
    const csv = buildFilesCsv([
      { ...baseItem, name: "Archive", isFolder: true, size: 0 },
      { ...baseItem, name: "b.txt", size: 0 },
      { ...baseItem, name: "a.txt", size: 1536 },
    ]);
    expect(csv.split("\r\n")).toEqual([
      "Name,Type,Size,Last modified,Owner",
      "Archive,Folder,,2026-11-01T10:30:00.000Z,Olive Otter",
      "b.txt,File,0 B,2026-11-01T10:30:00.000Z,Olive Otter",
      "a.txt,File,1.5 KB,2026-11-01T10:30:00.000Z,Olive Otter",
      "",
    ]);
  });

  it("escapes commas, quotes and newlines in any column", () => {
    const csv = buildFilesCsv([
      { ...baseItem, name: 'Q4 "final", v2\nnotes.txt', ownerName: "Otter, Olive" },
    ]);
    expect(csv).toBe(
      "Name,Type,Size,Last modified,Owner\r\n" +
        '"Q4 ""final"", v2\nnotes.txt",File,2 KB,2026-11-01T10:30:00.000Z,"Otter, Olive"\r\n'
    );
  });
});

describe("filesCsvFilename", () => {
  it("uses the otterworks-files-YYYY-MM-DD.csv pattern", () => {
    expect(filesCsvFilename(new Date(2026, 0, 5, 12))).toBe("otterworks-files-2026-01-05.csv");
    expect(filesCsvFilename(new Date(2026, 10, 13, 9))).toBe("otterworks-files-2026-11-13.csv");
  });

  it("defaults to today's date", () => {
    expect(filesCsvFilename()).toMatch(/^otterworks-files-\d{4}-\d{2}-\d{2}\.csv$/);
  });
});

function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () =>
      resolve(new TextDecoder("utf-8", { ignoreBOM: true }).decode(reader.result as ArrayBuffer));
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(blob);
  });
}

describe("downloadCsv", () => {
  afterEach(() => vi.restoreAllMocks());

  it("downloads the CSV as a UTF-8 blob with the given file name", async () => {
    let blob: Blob | undefined;
    const createObjectURL = vi.fn((b: Blob) => {
      blob = b;
      return "blob:csv";
    });
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    let clicked: HTMLAnchorElement | undefined;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked = this;
    });

    downloadCsv("Name\r\nx\r\n", "otterworks-files-2026-11-13.csv");

    expect(clicked?.download).toBe("otterworks-files-2026-11-13.csv");
    expect(clicked?.href).toBe("blob:csv");
    expect(blob?.type).toBe("text/csv;charset=utf-8");
    expect(await readBlob(blob!)).toBe("\uFEFFName\r\nx\r\n");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:csv");
    expect(document.querySelector("a[download]")).toBeNull();
  });
});
