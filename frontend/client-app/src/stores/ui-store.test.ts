import { beforeEach, describe, expect, it } from "vitest";
import { UI_STORE_STORAGE_KEY, useUIStore } from "./ui-store";

function savedViewMode() {
  const raw = localStorage.getItem(UI_STORE_STORAGE_KEY);
  return raw ? JSON.parse(raw).state.viewMode : undefined;
}

describe("useUIStore view mode persistence", () => {
  beforeEach(() => {
    localStorage.clear();
    useUIStore.setState({ viewMode: "grid" });
    localStorage.clear();
  });

  it("defaults to grid when nothing is saved", async () => {
    await useUIStore.persist.rehydrate();
    expect(useUIStore.getState().viewMode).toBe("grid");
  });

  it("saves the selected view mode to localStorage", () => {
    useUIStore.getState().setViewMode("list");
    expect(savedViewMode()).toBe("list");

    useUIStore.getState().setViewMode("grid");
    expect(savedViewMode()).toBe("grid");
  });

  it("restores the saved view mode after a reload", async () => {
    useUIStore.getState().setViewMode("list");
    const saved = localStorage.getItem(UI_STORE_STORAGE_KEY);
    expect(saved).not.toBeNull();

    // Simulate a fresh page load: in-memory state is back to its default,
    // while the browser still holds the saved preference.
    useUIStore.setState({ viewMode: "grid" });
    localStorage.setItem(UI_STORE_STORAGE_KEY, saved as string);

    await useUIStore.persist.rehydrate();
    expect(useUIStore.getState().viewMode).toBe("list");
  });

  it("only persists the view mode", () => {
    useUIStore.getState().setSidebarOpen(false);
    useUIStore.getState().setViewMode("list");
    const raw = JSON.parse(localStorage.getItem(UI_STORE_STORAGE_KEY) ?? "{}");
    expect(raw.state).toEqual({ viewMode: "list" });
    useUIStore.getState().setSidebarOpen(true);
  });

  it("falls back to grid when the saved value is invalid", async () => {
    localStorage.setItem(
      UI_STORE_STORAGE_KEY,
      JSON.stringify({ state: { viewMode: "tiles" }, version: 0 }),
    );
    await useUIStore.persist.rehydrate();
    expect(useUIStore.getState().viewMode).toBe("grid");
  });
});
