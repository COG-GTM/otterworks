import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { ViewMode, SortConfig } from "@/types";

export const UI_STORE_STORAGE_KEY = "otter_ui_prefs";

interface UIState {
  sidebarOpen: boolean;
  viewMode: ViewMode;
  sortConfig: SortConfig;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  setViewMode: (mode: ViewMode) => void;
  setSortConfig: (config: SortConfig) => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      sidebarOpen: true,
      viewMode: "grid",
      sortConfig: { field: "updatedAt", direction: "desc" },
      toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
      setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
      setViewMode: (viewMode) => set({ viewMode }),
      setSortConfig: (sortConfig) => set({ sortConfig }),
    }),
    {
      name: UI_STORE_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ viewMode: state.viewMode }),
      merge: (persisted, current) => {
        const viewMode = (persisted as Partial<UIState> | undefined)?.viewMode;
        return viewMode === "grid" || viewMode === "list" ? { ...current, viewMode } : current;
      },
    },
  ),
);
