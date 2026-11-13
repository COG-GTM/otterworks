import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, Home } from "lucide-react";

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface BreadcrumbProps {
  items: BreadcrumbItem[];
}

const MAX_VISIBLE_ITEMS = 4;
const TRAILING_ITEMS = 2;

function Separator() {
  return <ChevronRight size={14} className="text-gray-400 shrink-0" aria-hidden="true" />;
}

function CrumbLabel({ item }: { item: BreadcrumbItem }) {
  if (item.href) {
    return (
      <Link
        to={item.href}
        title={item.label}
        className="block max-w-[10rem] truncate hover:text-gray-700 transition px-1"
      >
        {item.label}
      </Link>
    );
  }
  return (
    <span
      title={item.label}
      aria-current="page"
      className="block max-w-[14rem] truncate text-gray-900 font-medium px-1"
    >
      {item.label}
    </span>
  );
}

function HiddenItemsMenu({ items }: { items: BreadcrumbItem[] }) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  return (
    <span ref={containerRef} className="relative flex items-center">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-label="Show hidden folders"
        aria-haspopup="menu"
        aria-expanded={open}
        className="rounded px-1.5 hover:bg-gray-100 hover:text-gray-700 transition"
      >
        {"\u2026"}
      </button>
      {open && (
        <ul
          role="menu"
          aria-label="Hidden folders"
          className="absolute left-0 top-full z-20 mt-1 min-w-[10rem] max-w-xs rounded-md border border-gray-200 bg-white py-1 shadow-lg"
        >
          {items.map((item, index) => (
            <li key={`${item.href ?? item.label}-${index}`} role="none">
              {item.href ? (
                <Link
                  role="menuitem"
                  to={item.href}
                  title={item.label}
                  onClick={() => setOpen(false)}
                  className="block truncate px-3 py-1.5 text-gray-700 hover:bg-gray-50"
                >
                  {item.label}
                </Link>
              ) : (
                <span
                  role="menuitem"
                  aria-disabled="true"
                  title={item.label}
                  className="block truncate px-3 py-1.5 text-gray-500"
                >
                  {item.label}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </span>
  );
}

export function Breadcrumb({ items }: BreadcrumbProps) {
  const collapsed = items.length > MAX_VISIBLE_ITEMS;
  const leading = collapsed ? items.slice(0, 1) : items;
  const hidden = collapsed ? items.slice(1, items.length - TRAILING_ITEMS) : [];
  const trailing = collapsed ? items.slice(items.length - TRAILING_ITEMS) : [];

  return (
    <nav className="flex items-center gap-1 text-sm text-gray-500 min-w-0" aria-label="Breadcrumb">
      <Link
        to="/dashboard"
        className="hover:text-gray-700 transition p-1 shrink-0"
        aria-label="Home"
      >
        <Home size={16} />
      </Link>
      {leading.map((item, index) => (
        <span key={`lead-${index}`} className="flex items-center gap-1 min-w-0">
          <Separator />
          <CrumbLabel item={item} />
        </span>
      ))}
      {collapsed && (
        <span className="flex items-center gap-1">
          <Separator />
          <HiddenItemsMenu items={hidden} />
        </span>
      )}
      {trailing.map((item, index) => (
        <span key={`trail-${index}`} className="flex items-center gap-1 min-w-0">
          <Separator />
          <CrumbLabel item={item} />
        </span>
      ))}
    </nav>
  );
}
