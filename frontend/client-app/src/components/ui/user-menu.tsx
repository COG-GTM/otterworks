import {
  useEffect,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";
import { Settings, LogOut } from "lucide-react";
import { cn, getInitials } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";

interface UserMenuProps {
  align?: "left" | "right";
  placement?: "top" | "bottom";
  variant?: "light" | "dark";
  children?: ReactNode;
  className?: string;
}

export function UserMenu({
  align = "right",
  placement = "bottom",
  variant = "light",
  children,
  className,
}: UserMenuProps) {
  const { user, logout } = useAuthStore();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  useEffect(() => {
    if (open) {
      menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    }
  }, [open]);

  const menuItems = () =>
    Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []
    );

  const close = (restoreFocus = false) => {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  };

  const onBlur = (e: FocusEvent<HTMLDivElement>) => {
    if (!rootRef.current?.contains(e.relatedTarget as Node | null)) close();
  };

  const onTriggerKeyDown = (e: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setOpen(true);
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      close(true);
    }
  };

  const onMenuKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    const items = menuItems();
    if (items.length === 0) return;
    const index = items.indexOf(document.activeElement as HTMLElement);
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        items[(index + 1) % items.length].focus();
        break;
      case "ArrowUp":
        e.preventDefault();
        items[(index - 1 + items.length) % items.length].focus();
        break;
      case "Home":
        e.preventDefault();
        items[0].focus();
        break;
      case "End":
        e.preventDefault();
        items[items.length - 1].focus();
        break;
      case "Escape":
        e.preventDefault();
        close(true);
        break;
      case "Tab":
        close();
        break;
    }
  };

  if (!user) return null;

  const dark = variant === "dark";

  return (
    <div ref={rootRef} className={cn("relative", className)} onBlur={onBlur}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        onKeyDown={onTriggerKeyDown}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Open user menu"
        className={cn(
          "flex items-center gap-3 rounded transition w-full text-left",
          dark ? "hover:bg-otter-600" : "hover:bg-gray-100"
        )}
      >
        <div
          className={cn(
            "w-8 h-8 shrink-0 rounded-full flex items-center justify-center text-xs font-semibold",
            dark ? "bg-otter-500 text-white" : "bg-otter-600 text-white"
          )}
        >
          {getInitials(user.displayName)}
        </div>
        {children}
      </button>

      {open && (
        <div
          ref={menuRef}
          role="menu"
          onKeyDown={onMenuKeyDown}
          className={cn(
            "absolute z-50 w-56 rounded-md border bg-white shadow-lg py-1 text-sm text-gray-700",
            align === "right" ? "right-0" : "left-0",
            placement === "top" ? "bottom-full mb-2" : "top-full mt-2",
            "border-gray-200"
          )}
        >
          <div className="px-3 py-2 border-b border-gray-200">
            <p className="font-medium text-gray-900 truncate">{user.displayName}</p>
            <p className="text-xs text-gray-500 truncate">{user.email}</p>
          </div>
          <Link
            to="/settings"
            role="menuitem"
            onClick={() => close()}
            className="flex items-center gap-2 px-3 py-2 hover:bg-gray-100"
          >
            <Settings size={16} />
            Settings
          </Link>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              close();
              logout();
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-gray-100"
          >
            <LogOut size={16} />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
