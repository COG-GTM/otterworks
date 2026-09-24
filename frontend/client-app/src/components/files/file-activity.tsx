import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { Activity as ActivityIcon, Loader2 } from "lucide-react";
import { auditApi, authApi, type AuditEvent } from "@/lib/api";
import { formatActivityVerb } from "@/lib/activity-verb";
import { formatRelativeTime, getInitials, generateColor } from "@/lib/utils";

const PAGE_SIZE = 10;

/**
 * Reverse-chronological audit timeline for a file. Renders nothing when the
 * viewer is not allowed to read the file's history (403).
 */
export function FileActivity({ fileId }: Readonly<{ fileId: string }>) {
  const [page, setPage] = useState(1);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});

  const { data, isLoading, isFetching, error } = useQuery({
    queryKey: ["audit", "history", fileId, page],
    queryFn: () => auditApi.getResourceHistory(fileId, { page, size: PAGE_SIZE }),
    retry: (count, err) => !(isAxiosError(err) && err.response?.status === 403) && count < 2,
  });

  useEffect(() => {
    setPage(1);
    setEvents([]);
  }, [fileId]);

  useEffect(() => {
    if (!data) return;
    setEvents((prev) => {
      const seen = new Set(prev.map((e) => e.id));
      return [...prev, ...data.events.filter((e) => !seen.has(e.id))];
    });
  }, [data]);

  useEffect(() => {
    const ids = new Set<string>();
    events.forEach((e) => {
      if (e.userId && e.userId !== "system") ids.add(e.userId);
      if (e.details?.sharedWithUserId) ids.add(e.details.sharedWithUserId);
    });
    const missing = [...ids].filter((id) => !(id in names));
    if (missing.length === 0) return;

    Promise.allSettled(missing.map((id) => authApi.lookupUserById(id))).then((results) => {
      const resolved: Record<string, string> = {};
      results.forEach((result, i) => {
        if (result.status === "fulfilled") {
          resolved[missing[i]] = result.value.displayName || result.value.email;
        }
      });
      if (Object.keys(resolved).length > 0) {
        setNames((prev) => ({ ...prev, ...resolved }));
      }
    });
  }, [events, names]);

  if (isAxiosError(error) && error.response?.status === 403) return null;

  return (
    <div className="bg-white rounded-xl border border-gray-200 mt-6">
      <div className="px-5 py-4 border-b border-gray-200">
        <h2 className="text-sm font-medium text-gray-700 flex items-center gap-2">
          <ActivityIcon size={16} />
          Activity
        </h2>
      </div>

      {isLoading && events.length === 0 ? (
        <div className="px-5 py-6 flex items-center gap-2 text-sm text-gray-500">
          <Loader2 size={16} className="animate-spin" />
          Loading activity...
        </div>
      ) : events.length === 0 ? (
        <p className="px-5 py-6 text-sm text-gray-400">No activity yet for this file</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {events.map((event) => {
            const actorName = names[event.userId] ?? (event.userId === "system" ? "System" : event.userId.slice(0, 8));
            return (
              <li key={event.id} className="flex items-start gap-3 px-5 py-3">
                <div
                  className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0"
                  style={{ backgroundColor: generateColor(event.userId) }}
                >
                  {getInitials(actorName)}
                </div>
                <div className="min-w-0">
                  <p className="text-sm text-gray-900">
                    <span className="font-medium">{actorName}</span>{" "}
                    {formatActivityVerb(event, (id) => names[id])}
                  </p>
                  <p className="text-xs text-gray-500">{formatRelativeTime(event.timestamp)}</p>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {data?.hasMore && (
        <div className="px-5 py-3 border-t border-gray-100">
          <button
            onClick={() => setPage((p) => p + 1)}
            disabled={isFetching}
            className="text-sm text-otter-600 hover:underline disabled:opacity-50"
          >
            {isFetching ? "Loading..." : "Show more"}
          </button>
        </div>
      )}
    </div>
  );
}
