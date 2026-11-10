import { isAxiosError } from "axios";
import { format } from "date-fns";
import type { SharePolicy, ShareExpiryRequest } from "@/types";

export const NEVER_EXPIRES = "never";

export interface ExpiryOption {
  value: string;
  label: string;
}

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

// Durations offered in the share dialog, filtered by the workspace policy.
export const EXPIRY_PRESETS_SECONDS = [HOUR, DAY, 7 * DAY, 30 * DAY, 90 * DAY, 365 * DAY];

export function formatDuration(seconds: number): string {
  const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? "" : "s"}`;
  if (seconds === 365 * DAY) return "1 year";
  if (seconds % DAY === 0) return plural(seconds / DAY, "day");
  if (seconds % HOUR === 0) return plural(seconds / HOUR, "hour");
  if (seconds % MINUTE === 0) return plural(seconds / MINUTE, "minute");
  return plural(seconds, "second");
}

export function isAllowedExpiry(policy: SharePolicy, seconds: number): boolean {
  return seconds >= policy.minExpirySeconds && seconds <= policy.maxExpirySeconds;
}

/** Expiry choices allowed by the policy; the workspace default is always included. */
export function expiryOptions(policy: SharePolicy): ExpiryOption[] {
  const seconds = new Set(EXPIRY_PRESETS_SECONDS.filter((s) => isAllowedExpiry(policy, s)));
  if (policy.defaultExpirySeconds > 0) seconds.add(policy.defaultExpirySeconds);
  const options: ExpiryOption[] = [...seconds]
    .sort((a, b) => a - b)
    .map((s) => ({
      value: String(s),
      label: s === policy.defaultExpirySeconds ? `${formatDuration(s)} (default)` : formatDuration(s),
    }));
  if (policy.allowNever) options.push({ value: NEVER_EXPIRES, label: "Never" });
  return options;
}

export function defaultExpiryValue(policy: SharePolicy): string {
  return String(policy.defaultExpirySeconds);
}

export function toExpiryRequest(value: string): ShareExpiryRequest {
  return value === NEVER_EXPIRES ? { never: true } : { expires_in_seconds: Number(value) };
}

export function formatExpiresAt(expiresAt: string | null): string {
  return expiresAt ? `Expires ${format(new Date(expiresAt), "PPp")}` : "Never expires";
}

export function errorStatus(err: unknown): number | undefined {
  return isAxiosError(err) ? err.response?.status : undefined;
}

export function errorDetail(err: unknown): string | undefined {
  if (!isAxiosError(err)) return undefined;
  const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" ? detail : undefined;
}

/** User-facing message for a failed create/update/revoke call. */
export function shareLinkErrorMessage(err: unknown, action: "create" | "update" | "revoke"): string {
  const status = errorStatus(err);
  if (status === 403) return "Only the folder owner can manage share links.";
  if (status === 404) return action === "create" ? "Folder not found." : "Share link not found.";
  if (status === 409) return "This link has already expired or been revoked. Create a new link instead.";
  if (status === 422) {
    const data = isAxiosError(err)
      ? (err.response?.data as { min_expiry_seconds?: number; max_expiry_seconds?: number } | undefined)
      : undefined;
    if (data?.min_expiry_seconds && data?.max_expiry_seconds) {
      return `Choose an expiry between ${formatDuration(data.min_expiry_seconds)} and ${formatDuration(data.max_expiry_seconds)}.`;
    }
    return errorDetail(err) ?? "That expiry is not allowed by your workspace settings.";
  }
  const verb = { create: "create", update: "update", revoke: "revoke" }[action];
  return `Could not ${verb} the share link. Please try again.`;
}
