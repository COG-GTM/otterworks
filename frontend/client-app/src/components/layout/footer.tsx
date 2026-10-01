import { Link } from "react-router-dom";

export function Footer() {
  return (
    <footer className="border-t border-line bg-surface">
      <div className="mx-auto flex h-10 max-w-7xl items-center justify-center gap-2 px-4 text-xs text-slate-500">
        <span>© OtterWorks, Inc.</span>
        <span aria-hidden="true">·</span>
        <span>v{__APP_VERSION__}</span>
        <span aria-hidden="true">·</span>
        <Link to="/terms" className="hover:text-otter-300 hover:underline">
          Terms
        </Link>
        <span aria-hidden="true">·</span>
        <Link to="/privacy" className="hover:text-otter-300 hover:underline">
          Privacy
        </Link>
      </div>
    </footer>
  );
}
