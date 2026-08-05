import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  CHAOS_ADMIN_STATE_KEY,
  CHAOS_CLIENT_STATE_KEY,
  CHAOS_SCENARIOS,
  CHAOS_TTL_MS,
  activeChaosScenarios,
  chaosConsole,
  chaosError,
  injectChaosLatency,
  isChaosActive,
  resetChaos,
  resolveScenario,
  setChaosActive,
} from "./chaos";

function installLocalStorage(): void {
  const store = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
    key: (i: number) => [...store.keys()][i] ?? null,
    get length() {
      return store.size;
    },
  } satisfies Storage);
}

describe("client-side chaos flag store", () => {
  beforeEach(() => {
    installLocalStorage();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("is inert until a scenario is enabled", () => {
    expect(activeChaosScenarios()).toEqual([]);
    expect(isChaosActive(CHAOS_SCENARIOS.searchSuggest500)).toBe(false);
  });

  it("resolves both the service name and the canonical Redis key", () => {
    expect(resolveScenario("file-service")).toBe(CHAOS_SCENARIOS.fileUploadS3Error);
    expect(resolveScenario("chaos:file-service:upload_s3_error")).toBe(
      CHAOS_SCENARIOS.fileUploadS3Error,
    );
    expect(resolveScenario("nope")).toBeNull();
  });

  it("activates only the scenario that was enabled", () => {
    setChaosActive("search-service", true);
    expect(isChaosActive(CHAOS_SCENARIOS.searchSuggest500)).toBe(true);
    expect(isChaosActive(CHAOS_SCENARIOS.fileUploadS3Error)).toBe(false);
  });

  it("reads the admin dashboard's boolean-per-service state", () => {
    localStorage.setItem(CHAOS_ADMIN_STATE_KEY, JSON.stringify({ "document-service": true }));
    expect(isChaosActive(CHAOS_SCENARIOS.documentSlowQueries)).toBe(true);
  });

  it("never writes the admin dashboard's key", () => {
    localStorage.setItem(CHAOS_ADMIN_STATE_KEY, JSON.stringify({ "file-service": true }));
    setChaosActive("search-service", true);
    isChaosActive(CHAOS_SCENARIOS.fileUploadS3Error);
    setChaosActive("search-service", false);
    resetChaos();
    expect(JSON.parse(localStorage.getItem(CHAOS_ADMIN_STATE_KEY) ?? "{}")).toEqual({
      "file-service": true,
    });
  });

  it("turns an admin-set flag off locally without erasing the admin's record", () => {
    localStorage.setItem(CHAOS_ADMIN_STATE_KEY, JSON.stringify({ "file-service": true }));
    expect(isChaosActive(CHAOS_SCENARIOS.fileUploadS3Error)).toBe(true);
    setChaosActive("file-service", false);
    expect(isChaosActive(CHAOS_SCENARIOS.fileUploadS3Error)).toBe(false);
    expect(JSON.parse(localStorage.getItem(CHAOS_ADMIN_STATE_KEY) ?? "{}")).toEqual({
      "file-service": true,
    });
  });

  it("re-arms with a fresh TTL after the admin clears and re-sets a flag", () => {
    vi.useFakeTimers();
    localStorage.setItem(CHAOS_ADMIN_STATE_KEY, JSON.stringify({ "file-service": true }));
    expect(isChaosActive(CHAOS_SCENARIOS.fileUploadS3Error)).toBe(true);
    vi.advanceTimersByTime(CHAOS_TTL_MS + 1);
    expect(isChaosActive(CHAOS_SCENARIOS.fileUploadS3Error)).toBe(false);

    localStorage.setItem(CHAOS_ADMIN_STATE_KEY, JSON.stringify({}));
    expect(isChaosActive(CHAOS_SCENARIOS.fileUploadS3Error)).toBe(false);
    localStorage.setItem(CHAOS_ADMIN_STATE_KEY, JSON.stringify({ "file-service": true }));
    expect(isChaosActive(CHAOS_SCENARIOS.fileUploadS3Error)).toBe(true);
  });

  it("still expires flags when localStorage writes are rejected", () => {
    vi.useFakeTimers();
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    setChaosActive("file-service", true, 1000);
    expect(isChaosActive(CHAOS_SCENARIOS.fileUploadS3Error)).toBe(true);
    vi.advanceTimersByTime(1001);
    expect(isChaosActive(CHAOS_SCENARIOS.fileUploadS3Error)).toBe(false);
  });

  it("expires flags like the server-side Redis TTL", () => {
    vi.useFakeTimers();
    setChaosActive("notification-service", true, 1000);
    expect(isChaosActive(CHAOS_SCENARIOS.notificationStrictSchema)).toBe(true);
    vi.advanceTimersByTime(1001);
    expect(isChaosActive(CHAOS_SCENARIOS.notificationStrictSchema)).toBe(false);
  });

  it("expires an admin-set flag that carries no expiry of its own", () => {
    vi.useFakeTimers();
    localStorage.setItem(CHAOS_ADMIN_STATE_KEY, JSON.stringify({ "file-service": true }));
    expect(isChaosActive(CHAOS_SCENARIOS.fileUploadS3Error)).toBe(true);

    vi.advanceTimersByTime(CHAOS_TTL_MS + 1);
    expect(isChaosActive(CHAOS_SCENARIOS.fileUploadS3Error)).toBe(false);
  });

  it("forgets a client-armed scenario once it lapses", () => {
    vi.useFakeTimers();
    setChaosActive("file-service", true, 1000);
    vi.advanceTimersByTime(1001);
    expect(isChaosActive(CHAOS_SCENARIOS.fileUploadS3Error)).toBe(false);
    expect(JSON.parse(localStorage.getItem(CHAOS_CLIENT_STATE_KEY) ?? "{}")).toEqual({});
  });

  it("clears every scenario on reset", () => {
    setChaosActive("search-service", true);
    setChaosActive("file-service", true);
    resetChaos();
    expect(activeChaosScenarios()).toEqual([]);
  });

  it("survives unparseable stored state", () => {
    localStorage.setItem(CHAOS_ADMIN_STATE_KEY, "not json");
    localStorage.setItem(CHAOS_CLIENT_STATE_KEY, "[]");
    expect(isChaosActive(CHAOS_SCENARIOS.searchSuggest500)).toBe(false);
  });

  it("honours an admin flag even when its own state is corrupt", () => {
    localStorage.setItem(CHAOS_ADMIN_STATE_KEY, JSON.stringify({ "search-service": true }));
    localStorage.setItem(CHAOS_CLIENT_STATE_KEY, "[]");
    expect(isChaosActive(CHAOS_SCENARIOS.searchSuggest500)).toBe(true);
  });

  it("reports unknown scenario names instead of silently arming nothing", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(setChaosActive("files-service", true)).toBe(false);
    expect(activeChaosScenarios()).toEqual([]);

    expect(chaosConsole.enable("files-service")).toEqual([]);
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('unknown scenario "files-service"'));
    warn.mockRestore();
  });

  it("builds an error indistinguishable from a failed axios request", () => {
    const error = chaosError(CHAOS_SCENARIOS.fileUploadS3Error, {
      method: "post",
      url: "/files/upload",
      status: 500,
      statusText: "Internal Server Error",
      data: { error: "storage_error", message: "S3 error: NoSuchBucket" },
    });
    expect(error.isAxiosError).toBe(true);
    expect(error.response?.status).toBe(500);
    expect(error.response?.data).toMatchObject({ error: "storage_error" });
    expect(error.chaosScenario).toBe(CHAOS_SCENARIOS.fileUploadS3Error);
  });

  it("only delays document reads while the slow-query flag is active", async () => {
    const started = Date.now();
    await injectChaosLatency(CHAOS_SCENARIOS.documentSlowQueries);
    expect(Date.now() - started).toBeLessThan(500);

    vi.useFakeTimers();
    setChaosActive("document-service", true);
    const pending = injectChaosLatency(CHAOS_SCENARIOS.documentSlowQueries);
    let settled = false;
    void pending.then(() => {
      settled = true;
    });
    await vi.advanceTimersByTimeAsync(2999);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(2001);
    await pending;
    expect(settled).toBe(true);
  });
});
