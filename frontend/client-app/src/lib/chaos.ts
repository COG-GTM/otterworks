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

/**
 * The admin dashboard's Demo Controls state. Read-only here: an admin toggle
 * arms the browser dupe too, but the client never writes this key, so a
 * browser-only flag can't make the operator UI report the service as broken.
 */
export const CHAOS_ADMIN_STATE_KEY = "ow_admin_chaos_state";

/** Everything this module writes, including expiries. */
export const CHAOS_CLIENT_STATE_KEY = "ow_client_chaos_state";

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

/**
 * `{ "search-service": true }`, the shape the admin dashboard writes. Flags are
 * also accepted under the full scenario key.
 */
type AdminChaosState = Record<string, boolean>;

/**
 * `source` records who armed the scenario: a `client` entry disappears when it
 * lapses, an `admin` entry is the client's own view of a flag it does not own
 * (stamped on first sight, kept once lapsed so it is not re-stamped forever).
 */
interface ChaosEntry {
  expiresAt: number;
  source: "client" | "admin";
}

type ClientChaosState = Record<string, ChaosEntry>;

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

function readJson<T extends object>(key: string): T {
  const storage = getStorage();
  if (!storage) return {} as T;
  try {
    const raw = storage.getItem(key);
    if (!raw) return {} as T;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {} as T;
    return parsed as T;
  } catch {
    return {} as T;
  }
}

function writeJson(key: string, value: object): void {
  const storage = getStorage();
  if (!storage) return;
  try {
    storage.setItem(key, JSON.stringify(value));
  } catch {
    /* private-mode / quota errors must never break the app */
  }
}

/** Fallback for private mode / quota errors, so a flag can still time out. */
let memoryState: ClientChaosState | null = null;

function readClientState(): ClientChaosState {
  return memoryState ?? readJson<ClientChaosState>(CHAOS_CLIENT_STATE_KEY);
}

function writeClientState(state: ClientChaosState): void {
  writeJson(CHAOS_CLIENT_STATE_KEY, state);
  const persisted = readJson<ClientChaosState>(CHAOS_CLIENT_STATE_KEY);
  memoryState = JSON.stringify(persisted) === JSON.stringify(state) ? null : state;
}

function adminFlagSet(scenario: ChaosScenarioKey): boolean {
  const state = readJson<AdminChaosState>(CHAOS_ADMIN_STATE_KEY);
  return Boolean(state[scenario]) || Boolean(state[serviceOf(scenario)]);
}

/** Resolve a service name (`file-service`) or full Redis key to a scenario key. */
export function resolveScenario(input: string): ChaosScenarioKey | null {
  const match = ALL_SCENARIOS.find((s) => s === input || serviceOf(s) === input);
  return match ?? null;
}

/**
 * A flag set by the admin dashboard carries no expiry (it only clears the key on
 * "Reset All"), so the client stamps one the first time it sees the flag: chaos
 * lapses in the browser like the Redis flag lapses on the server, instead of
 * degrading that browser forever.
 */
export function isChaosActive(scenarioKey: string): boolean {
  const scenario = resolveScenario(scenarioKey);
  if (!scenario) return false;

  const service = serviceOf(scenario);
  const state = readClientState();
  const entry = state[service];
  const fromAdmin = adminFlagSet(scenario);

  if (entry && (entry.source === "client" || fromAdmin)) {
    if (entry.expiresAt > Date.now()) return true;
    if (entry.source === "client") {
      const { [service]: _lapsed, ...rest } = state;
      writeClientState(rest);
    }
    return false;
  }

  if (entry) {
    // The admin cleared the flag; drop our stamp so a re-toggle starts a new TTL.
    const { [service]: _stale, ...rest } = state;
    writeClientState(rest);
  }
  if (!fromAdmin) return false;

  writeClientState({ ...state, [service]: { expiresAt: Date.now() + CHAOS_TTL_MS, source: "admin" } });
  return true;
}

export function activeChaosScenarios(): ChaosScenarioKey[] {
  return ALL_SCENARIOS.filter(isChaosActive);
}

export function setChaosActive(scenarioKey: string, active: boolean, ttlMs = CHAOS_TTL_MS): boolean {
  const scenario = resolveScenario(scenarioKey);
  if (!scenario) return false;
  const service = serviceOf(scenario);
  const state = readClientState();

  if (active) {
    writeClientState({ ...state, [service]: { expiresAt: Date.now() + ttlMs, source: "client" } });
    return true;
  }

  if (adminFlagSet(scenario)) {
    // Can't retract someone else's flag, so record it as already lapsed here.
    writeClientState({ ...state, [service]: { expiresAt: 0, source: "admin" } });
  } else {
    const { [service]: _off, ...rest } = state;
    writeClientState(rest);
  }
  return true;
}

export function resetChaos(): void {
  memoryState = null;
  for (const scenario of ALL_SCENARIOS) {
    setChaosActive(scenario, false);
  }
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

/**
 * Mirrors document-service's `_maybe_inject_latency`: 3-5s before the read resolves.
 * Additive with the server's: if the Redis flag is set as well, a read waits for both.
 */
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

function warnUnknownScenario(name: string): void {
  console.warn(
    `[chaos] unknown scenario "${name}" — expected one of: ${ALL_SCENARIOS.map(serviceOf).join(", ")}`,
  );
}

export const chaosConsole: ChaosConsole = {
  scenarios: CHAOS_SCENARIOS,
  enable: (scenario, ttlMs) => {
    if (!setChaosActive(scenario, true, ttlMs)) warnUnknownScenario(scenario);
    return activeChaosScenarios();
  },
  disable: (scenario) => {
    if (!setChaosActive(scenario, false)) warnUnknownScenario(scenario);
    return activeChaosScenarios();
  },
  reset: () => {
    resetChaos();
    return activeChaosScenarios();
  },
  active: activeChaosScenarios,
};

/** Drop the param once applied, so a reload doesn't keep restarting the TTL. */
function stripChaosParam(): void {
  const url = new URL(window.location.href);
  url.searchParams.delete("chaos");
  window.history.replaceState(window.history.state, "", url.toString());
}

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
    stripChaosParam();
    return;
  }
  for (const name of requested.split(",")) {
    if (!setChaosActive(name.trim(), true)) warnUnknownScenario(name.trim());
  }
  stripChaosParam();
}
