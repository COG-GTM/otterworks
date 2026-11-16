import { FILE_TYPE_FILTERS, type FileTypeFilter } from "@/lib/file-type";
import { cn } from "@/lib/utils";

interface FileTypeFilterBarProps {
  value: FileTypeFilter;
  onChange: (value: FileTypeFilter) => void;
}

export function FileTypeFilterBar({ value, onChange }: Readonly<FileTypeFilterBarProps>) {
  return (
    <div role="group" aria-label="Filter by file type" className="flex flex-wrap items-center gap-2">
      {FILE_TYPE_FILTERS.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className={cn(
              "px-3 py-1.5 text-sm rounded-full border transition",
              active
                ? "bg-otter-600 border-otter-600 text-white"
                : "bg-white border-gray-300 text-gray-700 hover:bg-gray-50"
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
