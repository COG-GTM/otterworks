import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Search, X } from "lucide-react";

export function SearchBar() {
  const [query, setQuery] = useState("");
  const navigate = useNavigate();

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (query.trim()) {
        navigate(`/search?q=${encodeURIComponent(query.trim())}`);
      }
    },
    [query, navigate]
  );

  return (
    <form onSubmit={handleSubmit} className="relative w-full">
      <Search
        size={18}
        className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"
      />
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search files, documents..."
        className="w-full pl-10 pr-10 py-2 bg-surface-raised border border-line rounded-lg text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-otter-500 focus:border-transparent transition"
      />
      {query && (
        <button
          type="button"
          onClick={() => setQuery("")}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
        >
          <X size={16} />
        </button>
      )}
    </form>
  );
}
