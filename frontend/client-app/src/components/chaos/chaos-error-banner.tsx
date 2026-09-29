import { AlertOctagon, FileWarning, ExternalLink, X } from "lucide-react";
import { cn } from "@/lib/utils";

type BannerVariant = "error" | "warning";

interface ChaosErrorBannerProps {
  title: string;
  message: string;
  actionHref?: string;
  actionLabel?: string;
  onDismiss?: () => void;
  className?: string;
  variant?: BannerVariant;
}

const VARIANT_STYLES: Record<
  BannerVariant,
  { container: string; message: string; action: string; dismiss: string }
> = {
  error: {
    container: "bg-red-600 text-white border-red-700",
    message: "text-red-100",
    action: "hover:text-red-100",
    dismiss: "text-red-100 hover:text-white",
  },
  warning: {
    container: "bg-amber-400 text-amber-950 border-amber-500",
    message: "text-amber-900",
    action: "hover:text-amber-800",
    dismiss: "text-amber-900 hover:text-amber-950",
  },
};

// Large full-width banner used to surface failures prominently in the UI
// (vs. the small per-item inline error text).
export function ChaosErrorBanner({
  title,
  message,
  actionHref,
  actionLabel,
  onDismiss,
  className,
  variant = "error",
}: ChaosErrorBannerProps) {
  const styles = VARIANT_STYLES[variant];
  const Icon = variant === "warning" ? FileWarning : AlertOctagon;
  return (
    <div
      role="alert"
      className={cn(
        "w-full flex items-start gap-4 p-5 rounded-xl border-2 shadow-lg",
        styles.container,
        className,
      )}
    >
      <Icon size={36} className="flex-shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <p className="text-lg font-bold uppercase tracking-wide">{title}</p>
        <p className={cn("text-sm mt-1", styles.message)}>{message}</p>
        {actionHref && (
          <a
            href={actionHref}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(
              "inline-flex items-center gap-1.5 mt-2 text-sm font-semibold underline underline-offset-2",
              styles.action,
            )}
          >
            {actionLabel ?? "View details"}
            <ExternalLink size={14} />
          </a>
        )}
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className={cn("p-1 transition flex-shrink-0", styles.dismiss)}
          title="Dismiss"
        >
          <X size={20} />
        </button>
      )}
    </div>
  );
}
