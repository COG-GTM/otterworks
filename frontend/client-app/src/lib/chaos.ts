import { AxiosError, AxiosHeaders } from "axios";
import type { AxiosResponse, InternalAxiosRequestConfig } from "axios";
import { API_BASE_URL } from "./api-client";

/**
 * Client-side dupe of the server-side chaos scenarios.
 *
 * The services in `services/*` read these same flags from Redis (see
 * `scripts/bug-catalog.yaml`); this module lets the browser reproduce the exact
 * same failures without a backend, so the demo works against any stack.
 * Scenario identifiers are the canonical Redis key strings so a flag means the
 * same thing on both sides.
 */

/** localStorage key, shared with the admin dashboard's Demo Controls panel. */
export const CHAOS_STATE_KEY = "ow_admin_chaos_state";

export const CHAOS_SCENARIOS = {
  searchSuggest500: "chaos:search-service:suggest_500",
  fileUploadS3Error: "chaos:file-service:upload_s3_error",
  documentSlowQueries: "chaos:document-service:slow_queries",
  notificationStrictSchema: "chaos:notification-service:consumer_strict_schema",
} as const;

export type ChaosScenarioKey = (typeof CHAOS_SCENARIOS)[keyof typeof CHAOS_SCENARIOS];

const ALL_SCENARIOS: ChaosScenarioKey[] = Object.values(CHAOS_SCENARIOS);

/** Matches ChaosController::CHAOS_TTL_SECONDS so client flags expire like the Redis ones. */
export const CHAOS_TTL_MS = 600_000;

/** Latency window the document-service injects when `slow_queries` is active. */
const SLOW_QUERY_MIN_MS = 3000;
const SLOW_QUERY_MAX_MS = 5000;

interface ChaosEntry {
  active: boolean;
  expiresAt?: number;
}

/**
 * The admin dashboard writes `{ "search-service": true }`; entries written here
 * carry an expiry, so both shapes are accepted under either the service name or
 * the full scenario key.
 */
type ChaosState = Record<string, boolean | ChaosEntry>;

function serviceOf(scenarioKey: string): string {
  return scenarioKey.split(":")[1] ?? "";
}

function getStorage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

function readState(): ChaosState {
  const storage = getStorage();
  if (!storage) return {};
  try {
    const raw = storage.getItem(CHAOS_STATE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return parsed as ChaosState;
  } catch {
    return {};
  }
}

function writeState(state: ChaosState): void {
  const storage = getStorage();
  if (!storage) return;
  try {
    storage.setItem(CHAOS_STATE_KEY, JSON.stringify(state));
  } catch {
    /* private-mode / quota errors must never break the app */
  }
}

function entryActive(value: boolean | ChaosEntry | undefined): boolean {
  if (typeof value === "boolean") return value;
  if (!value || typeof value !== "object") return false;
  if (!value.active) return false;
  return value.expiresAt === undefined || value.expiresAt > Date.now();
}

/** Resolve a service name (`file-service`) or full Redis key to a scenario key. */
export function resolveScenario(input: string): ChaosScenarioKey | null {
  const match = ALL_SCENARIOS.find((s) => s === input || serviceOf(s) === input);
  return match ?? null;
}

export function isChaosActive(scenarioKey: string): boolean {
  const state = readState();
  return entryActive(state[scenarioKey]) || entryActive(state[serviceOf(scenarioKey)]);
}

export function activeChaosScenarios(): ChaosScenarioKey[] {
  return ALL_SCENARIOS.filter(isChaosActive);
}

export function setChaosActive(scenarioKey: string, active: boolean, ttlMs = CHAOS_TTL_MS): void {
  const scenario = resolveScenario(scenarioKey);
  if (!scenario) return;
  const state = readState();
  if (active) {
    state[scenario] = { active: true, expiresAt: Date.now() + ttlMs };
  } else {
    delete state[scenario];
    delete state[serviceOf(scenario)];
  }
  writeState(state);
}

export function resetChaos(): void {
  const state = readState();
  for (const scenario of ALL_SCENARIOS) {
    delete state[scenario];
    delete state[serviceOf(scenario)];
  }
  writeState(state);
}

export interface ChaosAxiosError extends AxiosError {
  chaosScenario: ChaosScenarioKey;
}

/**
 * Build the failed-request error a caller would get from axios, so callers
 * cannot tell the client-side dupe from the real server-side failure.
 */
export function chaosError(
  scenarioKey: ChaosScenarioKey,
  request: { method: string; url: string; status: number; statusText: string; data: unknown },
): ChaosAxiosError {
  const config = {
    method: request.method,
    url: request.url,
    baseURL: API_BASE_URL,
    headers: new AxiosHeaders(),
  } as InternalAxiosRequestConfig;

  const response: AxiosResponse = {
    data: request.data,
    status: request.status,
    statusText: request.statusText,
    headers: new AxiosHeaders({ "content-type": "application/json" }),
    config,
  };

  const error = new AxiosError(
    `Request failed with status code ${request.status}`,
    AxiosError.ERR_BAD_RESPONSE,
    config,
    {},
    response,
  );
  return Object.assign(error, { chaosScenario: scenarioKey });
}

/** Mirrors document-service's `_maybe_inject_latency`: 3-5s before the read resolves. */
export async function injectChaosLatency(scenarioKey: ChaosScenarioKey): Promise<void> {
  if (!isChaosActive(scenarioKey)) return;
  const delay = SLOW_QUERY_MIN_MS + Math.random() * (SLOW_QUERY_MAX_MS - SLOW_QUERY_MIN_MS);
  await new Promise((resolve) => setTimeout(resolve, delay));
}

export interface ChaosConsole {
  scenarios: typeof CHAOS_SCENARIOS;
  enable: (scenario: string, ttlMs?: number) => ChaosScenarioKey[];
  disable: (scenario: string) => ChaosScenarioKey[];
  reset: () => ChaosScenarioKey[];
  active: () => ChaosScenarioKey[];
}

declare global {
  interface Window {
    otterChaos?: ChaosConsole;
  }
}

export const chaosConsole: ChaosConsole = {
  scenarios: CHAOS_SCENARIOS,
  enable: (scenario, ttlMs) => {
    setChaosActive(scenario, true, ttlMs);
    return activeChaosScenarios();
  },
  disable: (scenario) => {
    setChaosActive(scenario, false);
    return activeChaosScenarios();
  },
  reset: () => {
    resetChaos();
    return activeChaosScenarios();
  },
  active: activeChaosScenarios,
};

/**
 * Expose the toggles to the browser console (`otterChaos.enable('file-service')`)
 * and honour `?chaos=file-service,document-service` so a demo can be linked to.
 */
export function installChaosConsole(): void {
  if (typeof window === "undefined") return;
  window.otterChaos = chaosConsole;
  const requested = new URLSearchParams(window.location.search).get("chaos");
  if (!requested) return;
  if (requested === "reset" || requested === "off") {
    resetChaos();
    return;
  }
  for (const name of requested.split(",")) {
    setChaosActive(name.trim(), true);
  }
}
