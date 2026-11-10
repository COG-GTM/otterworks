import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Link2 } from "lucide-react";
import { documentsApi } from "@/lib/api";
import type { ShareLink } from "@/types";

function shareUrl(link: ShareLink): string {
  return `${window.location.origin}/s/${link.documentId}?token=${encodeURIComponent(link.token)}`;
}

function errorDetail(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : "Could not create share link";
}

export function ShareLinkPanel({ documentId }: { documentId: string }) {
  const queryClient = useQueryClient();
  const [days, setDays] = useState<number | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const { data: policy } = useQuery({
    queryKey: ["share-policy"],
    queryFn: () => documentsApi.getSharePolicy(),
  });
  const { data: links = [] } = useQuery({
    queryKey: ["share-links", documentId],
    queryFn: () => documentsApi.listShareLinks(documentId),
  });

  useEffect(() => {
    if (policy && days === null) setDays(policy.defaultExpiryDays);
  }, [policy, days]);

  const createLink = useMutation({
    mutationFn: () => documentsApi.createShareLink(documentId, days ?? undefined),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["share-links", documentId] }),
  });

  const copy = (link: ShareLink) => {
    navigator.clipboard.writeText(shareUrl(link));
    setCopiedId(link.id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const outOfBounds =
    !!policy && days !== null && (days < policy.minExpiryDays || days > policy.maxExpiryDays);

  return (
    <div className="space-y-2 pt-2 border-t border-gray-100" data-testid="share-link-panel">
      <div className="flex items-end gap-2">
        <label className="flex-1 text-sm text-gray-700">
          Link expires in (days)
          <input
            type="number"
            aria-label="Link expiry in days"
            min={policy?.minExpiryDays}
            max={policy?.maxExpiryDays}
            value={days ?? ""}
            onChange={(e) => setDays(e.target.value === "" ? null : Number(e.target.value))}
            className="mt-1 w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-otter-500"
          />
        </label>
        <button
          onClick={() => createLink.mutate()}
          disabled={createLink.isPending || days === null}
          className="flex items-center gap-1.5 px-3 py-2 text-sm text-white bg-otter-600 rounded-lg hover:bg-otter-700 disabled:opacity-50 transition"
        >
          <Link2 size={14} />
          Create link
        </button>
      </div>
      {policy && (
        <p className={outOfBounds ? "text-xs text-red-600" : "text-xs text-gray-500"}>
          Workspace default {policy.defaultExpiryDays} days; allowed {policy.minExpiryDays}–
          {policy.maxExpiryDays} days.
        </p>
      )}
      {createLink.isError && (
        <p className="text-sm text-red-600" role="alert">{errorDetail(createLink.error)}</p>
      )}
      {links.length > 0 && (
        <ul className="space-y-1">
          {links.map((link) => (
            <li key={link.id} className="flex items-center justify-between gap-2 text-sm">
              <span className={link.expired ? "text-red-600" : "text-gray-700"}>
                {link.expired ? "Expired" : "Expires"} {new Date(link.expiresAt).toLocaleString()}
              </span>
              {!link.expired && (
                <button
                  onClick={() => copy(link)}
                  className="flex items-center gap-1 px-2 py-1 text-xs text-gray-600 bg-gray-50 rounded hover:bg-gray-100"
                >
                  {copiedId === link.id ? <Check size={12} /> : <Copy size={12} />}
                  {copiedId === link.id ? "Copied!" : "Copy link"}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
