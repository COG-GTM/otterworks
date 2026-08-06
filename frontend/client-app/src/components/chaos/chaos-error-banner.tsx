import { AlertOctagon, X } from "lucide-react";

interface ChaosErrorBannerProps {
  title: string;
  message: string;
  onDismiss?: () => void;
}

// Large full-width red error banner used to surface chaos-scenario failures
// prominently in the UI (vs. the small per-item inline error text).
export function ChaosErrorBanner({ title, message, onDismiss }: ChaosErrorBannerProps) {
  return (
    <div
      role="alert"
      className="w-full flex items-start gap-4 p-5 bg-red-600 text-white rounded-xl border-2 border-red-700 shadow-lg"
    >
      <AlertOctagon size={36} className="flex-shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <p className="text-lg font-bold uppercase tracking-wide">{title}</p>
        <p className="text-sm mt-1 text-red-100">{message}</p>
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="p-1 text-red-100 hover:text-white transition flex-shrink-0"
          title="Dismiss"
        >
          <X size={20} />
        </button>
      )}
    </div>
  );
}
