import { useEffect, useRef, useCallback } from "react";
import { AlertTriangle } from "lucide-react";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "destructive" | "default";
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  variant = "default",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onCancel();
        return;
      }
      if (e.key === "Tab" && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    },
    [onCancel]
  );

  useEffect(() => {
    if (open) {
      document.addEventListener("keydown", handleKeyDown);
      cancelRef.current?.focus();
      return () => document.removeEventListener("keydown", handleKeyDown);
    }
  }, [open, handleKeyDown]);

  if (!open) return null;

  const isDestructive = variant === "destructive";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      aria-describedby="confirm-dialog-description"
    >
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/70 transition-opacity"
        onClick={onCancel}
        aria-hidden="true"
      />

      {/* Dialog */}
      <div
        ref={dialogRef}
        className="relative bg-surface border border-line rounded-xl shadow-xl shadow-black/50 max-w-md w-full mx-4 p-6 space-y-4"
      >
        <div className="flex items-start gap-4">
          {isDestructive && (
            <div className="w-10 h-10 rounded-full bg-red-500/15 flex items-center justify-center flex-shrink-0">
              <AlertTriangle size={20} className="text-red-400" />
            </div>
          )}
          <div className="flex-1 min-w-0">
            <h2
              id="confirm-dialog-title"
              className="text-lg font-semibold text-slate-100"
            >
              {title}
            </h2>
            <p
              id="confirm-dialog-description"
              className="text-sm text-slate-400 mt-1"
            >
              {description}
            </p>
          </div>
        </div>

        <div className="flex justify-end gap-3 pt-2">
          <button
            ref={cancelRef}
            onClick={onCancel}
            className="px-4 py-2 text-sm font-medium text-slate-200 bg-surface-raised border border-line rounded-lg hover:bg-surface-hover transition"
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            className={
              isDestructive
                ? "px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg hover:bg-red-500 transition"
                : "px-4 py-2 text-sm font-medium text-white bg-otter-500 rounded-lg hover:bg-otter-400 transition"
            }
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
