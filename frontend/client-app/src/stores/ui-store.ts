import { create } from "zustand";
import type { ViewMode, SortConfig } from "@/types";

interface UIState {
  sidebarOpen: boolean;
  viewMode: ViewMode;
  sortConfig: SortConfig;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  setViewMode: (mode: ViewMode) => void;
  setSortConfig: (config: SortConfig) => void;
}

// The drawer starts closed on phones, where it overlays the page.
const isWideScreen = () =>
  typeof window === "undefined" || window.matchMedia?.("(min-width: 1024px)").matches !== false;

export const useUIStore = create<UIState>((set) => ({
  sidebarOpen: isWideScreen(),
  viewMode: "grid",
  sortConfig: { field: "updatedAt", direction: "desc" },
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  setViewMode: (viewMode) => set({ viewMode }),
  setSortConfig: (sortConfig) => set({ sortConfig }),
}));
