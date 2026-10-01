import { Link } from "react-router-dom";

export function Footer() {
  return (
    <footer className="border-t border-gray-300 bg-white [.theme-dark_&]:border-line [.theme-dark_&]:bg-surface">
      <div className="mx-auto flex h-10 max-w-7xl items-center justify-center gap-2 px-4 text-xs text-gray-500 [.theme-dark_&]:text-slate-500">
        <span>© OtterWorks, Inc.</span>
        <span aria-hidden="true">·</span>
        <span>v{__APP_VERSION__}</span>
        <span aria-hidden="true">·</span>
        <Link to="/terms" className="hover:text-otter-600 hover:underline [.theme-dark_&]:hover:text-otter-300">
          Terms
        </Link>
        <span aria-hidden="true">·</span>
        <Link to="/privacy" className="hover:text-otter-600 hover:underline [.theme-dark_&]:hover:text-otter-300">
          Privacy
        </Link>
      </div>
    </footer>
  );
}
