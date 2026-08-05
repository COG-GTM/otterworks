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

/**
 * Expiries live in a client-owned key so `CHAOS_STATE_KEY` stays the plain
 * `Record<string, boolean>` the admin dashboard reads and counts.
 */
export const CHAOS_EXPIRY_KEY = "ow_client_chaos_expiry";

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
 * `{ "search-service": true }`, the shape the admin dashboard writes and reads.
 * Flags are also accepted under the full scenario key.
 */
type ChaosState = Record<string, boolean>;

/** `{ "search-service": <epoch ms> }` — when the client stops honouring a flag. */
type ChaosExpiries = Record<string, number>;

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

function readState(): ChaosState {
  return readJson<ChaosState>(CHAOS_STATE_KEY);
}

function writeState(state: ChaosState): void {
  writeJson(CHAOS_STATE_KEY, state);
}

function readExpiries(): ChaosExpiries {
  return readJson<ChaosExpiries>(CHAOS_EXPIRY_KEY);
}

function writeExpiries(expiries: ChaosExpiries): void {
  writeJson(CHAOS_EXPIRY_KEY, expiries);
}

function flagSet(state: ChaosState, scenario: ChaosScenarioKey): boolean {
  return Boolean(state[scenario]) || Boolean(state[serviceOf(scenario)]);
}

function clearFlag(scenario: ChaosScenarioKey): void {
  const state = readState();
  delete state[scenario];
  delete state[serviceOf(scenario)];
  writeState(state);
  const expiries = readExpiries();
  delete expiries[serviceOf(scenario)];
  writeExpiries(expiries);
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
  if (!flagSet(readState(), scenario)) return false;

  const service = serviceOf(scenario);
  const expiries = readExpiries();
  const expiresAt = expiries[service];

  if (typeof expiresAt !== "number") {
    writeExpiries({ ...expiries, [service]: Date.now() + CHAOS_TTL_MS });
    return true;
  }
  if (expiresAt <= Date.now()) {
    clearFlag(scenario);
    return false;
  }
  return true;
}

export function activeChaosScenarios(): ChaosScenarioKey[] {
  return ALL_SCENARIOS.filter(isChaosActive);
}

export function setChaosActive(scenarioKey: string, active: boolean, ttlMs = CHAOS_TTL_MS): boolean {
  const scenario = resolveScenario(scenarioKey);
  if (!scenario) return false;
  if (!active) {
    clearFlag(scenario);
    return true;
  }
  const service = serviceOf(scenario);
  writeState({ ...readState(), [service]: true });
  writeExpiries({ ...readExpiries(), [service]: Date.now() + ttlMs });
  return true;
}

export function resetChaos(): void {
  for (const scenario of ALL_SCENARIOS) {
    clearFlag(scenario);
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
    if (!setChaosActive(name.trim(), true)) {
      console.warn(
        `[chaos] unknown scenario "${name.trim()}" — expected one of: ${ALL_SCENARIOS.map(serviceOf).join(", ")}`,
      );
    }
  }
}
