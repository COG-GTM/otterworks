import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Clock, Link2Off, SearchX } from "lucide-react";
import { Logo } from "@/components/ui/logo";

/** Minimal public chrome for share-link recipients (no sidebar, no sign-in required). */
export function SharedLinkLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-otter-50">
      <header className="bg-white border-b border-gray-300 h-12">
        <div className="max-w-4xl mx-auto h-full px-4 flex items-center gap-2">
          <Link to="/" className="flex items-center gap-2">
            <Logo size={24} />
            <span className="text-sm font-semibold text-gray-900">OtterWorks</span>
          </Link>
        </div>
      </header>
      <main className="max-w-4xl mx-auto px-4 py-8">{children}</main>
    </div>
  );
}

const GONE_COPY = {
  title: "This link has expired",
  expired: "The link you followed is no longer active.",
  revoked: "The owner turned off this link.",
  hint: "Ask the person who shared it with you for a new link.",
};

/** Shown when the API answers 410 Gone for a share link (expired or revoked). */
export function ShareLinkExpired({ detail }: { detail?: string }) {
  const revoked = detail?.toLowerCase().includes("revoked");
  return (
    <StatusPanel
      icon={<Clock size={28} className="text-gray-400" />}
      title={GONE_COPY.title}
      lines={[revoked ? GONE_COPY.revoked : GONE_COPY.expired, GONE_COPY.hint]}
    />
  );
}

export function ShareLinkNotFound() {
  return (
    <StatusPanel
      icon={<SearchX size={28} className="text-gray-400" />}
      title="Link not found"
      lines={["Check that you copied the whole link."]}
    />
  );
}

export function ShareLinkError({ onRetry }: { onRetry: () => void }) {
  return (
    <StatusPanel
      icon={<Link2Off size={28} className="text-gray-400" />}
      title="Something went wrong"
      lines={["The shared folder could not be loaded."]}
      action={
        <button
          onClick={onRetry}
          className="px-4 py-2 bg-otter-600 text-white rounded-lg hover:bg-otter-700 transition text-sm font-medium"
        >
          Try again
        </button>
      }
    />
  );
}

function StatusPanel({
  icon,
  title,
  lines,
  action,
}: {
  icon: ReactNode;
  title: string;
  lines: string[];
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center text-center py-16 px-4 bg-white rounded-xl border border-gray-200">
      <div className="w-16 h-16 rounded-full bg-gray-100 flex items-center justify-center mb-4">{icon}</div>
      <h1 className="text-xl font-semibold text-gray-900 mb-2">{title}</h1>
      {lines.map((line) => (
        <p key={line} className="text-sm text-gray-500 max-w-sm">
          {line}
        </p>
      ))}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
