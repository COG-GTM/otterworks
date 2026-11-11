import axios from "axios";
import toast from "react-hot-toast";
import { create } from "zustand";
import { authApi } from "@/lib/api";
import { setAccessToken } from "@/lib/auth-token";
import type { User } from "@/types";

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  setUser: (user: User | null) => void;
  setLoading: (loading: boolean) => void;
  logout: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,
  setUser: (user) => set({ user, isAuthenticated: !!user, isLoading: false }),
  setLoading: (isLoading) => set({ isLoading }),
  logout: async () => {
    // auth-service must revoke the refresh token and clear its HttpOnly cookie; the page
    // cannot. If that fails, staying signed in is honest — a reload would restore it anyway.
    // A 401 means there is no live session left to revoke.
    try {
      await authApi.logout();
    } catch (err) {
      if (!(axios.isAxiosError(err) && err.response?.status === 401)) {
        toast.error("Sign out failed. Please try again.");
        return;
      }
    }
    setAccessToken(null);
    set({ user: null, isAuthenticated: false, isLoading: false });
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
  },
}));
