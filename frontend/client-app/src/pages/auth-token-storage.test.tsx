import { http, HttpResponse } from "msw";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import LoginPage from "./login";
import RegisterPage from "./register";
import { billingServer } from "../test-setup";

const TOKENS = {
  access_token: "access-from-server",
  refresh_token: "refresh-from-server",
  token_type: "Bearer",
  expires_in: 3600,
};

const PROFILE = { id: "u-1", email: "otter@example.com", display_name: "Otter" };

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/dashboard" element={<p>dashboard</p>} />
      </Routes>
    </MemoryRouter>
  );
}

function storedValues() {
  return Object.keys(localStorage).map((k) => localStorage.getItem(k));
}

describe("auth pages token storage", () => {
  beforeEach(() => {
    localStorage.clear();
    billingServer.use(
      http.post("http://localhost:3000/api/v1/auth/login", () => HttpResponse.json(TOKENS)),
      http.post("http://localhost:3000/api/v1/auth/register", () => HttpResponse.json(TOKENS)),
      http.get("http://localhost:3000/api/v1/auth/profile", () => HttpResponse.json(PROFILE))
    );
  });

  it("login keeps the access token and never persists the refresh token", async () => {
    localStorage.setItem("otter_refresh_token", "stale-refresh");
    renderAt("/login");
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "otter@example.com" } });
    fireEvent.change(screen.getByPlaceholderText("Enter your password"), {
      target: { value: "hunter22" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText("dashboard")).toBeInTheDocument();
    expect(localStorage.getItem("otter_access_token")).toBe("access-from-server");
    expect(localStorage.getItem("otter_refresh_token")).toBeNull();
    expect(storedValues()).not.toContain("refresh-from-server");
  });

  it("register keeps the access token and never persists the refresh token", async () => {
    renderAt("/register");
    fireEvent.change(screen.getByPlaceholderText("Jane Smith"), { target: { value: "Otter" } });
    fireEvent.change(screen.getByPlaceholderText("you@example.com"), {
      target: { value: "otter@example.com" },
    });
    fireEvent.change(screen.getByPlaceholderText("At least 8 characters"), {
      target: { value: "hunter2222" },
    });
    fireEvent.change(screen.getByPlaceholderText("Repeat your password"), {
      target: { value: "hunter2222" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => expect(screen.getByText("dashboard")).toBeInTheDocument());
    expect(localStorage.getItem("otter_access_token")).toBe("access-from-server");
    expect(localStorage.getItem("otter_refresh_token")).toBeNull();
    expect(storedValues()).not.toContain("refresh-from-server");
  });
});
