export function BillingAlert({
  message,
  onDismiss,
}: Readonly<{ message: string; onDismiss: () => void }>) {
  return (
    <div
      role="alert"
      className="flex items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
    >
      <span>{message}</span>
      <button
        type="button"
        aria-label="Dismiss error"
        onClick={onDismiss}
        className="rounded px-2 py-1 font-semibold hover:bg-red-100"
      >
        Dismiss
      </button>
    </div>
  );
}
