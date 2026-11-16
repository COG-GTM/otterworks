import toast from "react-hot-toast";
import { Link2 } from "lucide-react";

export function CopyLinkButton({ url }: Readonly<{ url?: string }>) {
  const handleCopy = async () => {
    const link = url ?? globalThis.location.href;
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("Clipboard API unavailable");
      }
      await navigator.clipboard.writeText(link);
      toast.success("Link copied");
    } catch {
      toast.error("Could not copy link. Please copy it from the address bar.");
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="flex items-center gap-2 px-3 py-2 text-sm text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition"
    >
      <Link2 size={16} />
      Copy link
    </button>
  );
}
