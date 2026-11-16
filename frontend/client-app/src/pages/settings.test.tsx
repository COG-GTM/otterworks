import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SettingsPage from "./settings";
import { authApi, settingsApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";
import { useUIStore } from "@/stores/ui-store";

vi.mock("@/lib/api", () => ({
  authApi: { updateProfile: vi.fn(), logout: vi.fn() },
  settingsApi: { get: vi.fn(), update: vi.fn() },
}));

// Keep the real sidebar (the navigation under test) but skip header widgets that hit the API.
vi.mock("@/components/layout/app-shell", async () => {
  const { Sidebar } = await import("@/components/layout/sidebar");
  return {
    AppShell: ({ children }: { children: ReactNode }) => (
      <>
        <Sidebar />
        <main>{children}</main>
      </>
    ),
  };
});

const USER = { id: "u1", displayName: "Olive Otter", email: "olive@otterworks.dev" };

function renderSettings() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: "/settings", element: <SettingsPage /> },
      { path: "/dashboard", element: <h1>Dashboard page</h1> },
    ],
    { initialEntries: ["/settings"] }
  );
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
  return router;
}

async function nameInput() {
  return (await screen.findByLabelText("Full name")) as HTMLInputElement;
}

function saveButton() {
  return screen.getByRole("button", { name: /save changes/i });
}

function fireBeforeUnload() {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event;
}

describe("SettingsPage unsaved profile changes", () => {
  beforeEach(() => {
    vi.mocked(settingsApi.get).mockResolvedValue({
      notificationEmail: true,
      notificationInApp: true,
      notificationDesktop: false,
    } as Awaited<ReturnType<typeof settingsApi.get>>);
    vi.mocked(authApi.updateProfile).mockImplementation(async (updates) => ({
      ...USER,
      ...updates,
    }));
    useAuthStore.setState({ user: USER, isAuthenticated: true, isLoading: false });
    useUIStore.setState({ sidebarOpen: true });
  });

  it("keeps Save disabled until the profile changes and again after reverting", async () => {
    renderSettings();
    const input = await nameInput();
    expect(input.value).toBe(USER.displayName);
    expect(saveButton()).toBeDisabled();

    fireEvent.change(input, { target: { value: "Olive O." } });
    await waitFor(() => expect(saveButton()).toBeEnabled());

    fireEvent.change(input, { target: { value: USER.displayName } });
    await waitFor(() => expect(saveButton()).toBeDisabled());
  });

  it("asks for confirmation before leaving via the sidebar with unsaved changes", async () => {
    const router = renderSettings();
    fireEvent.change(await nameInput(), { target: { value: "Olive O." } });
    await waitFor(() => expect(saveButton()).toBeEnabled());

    fireEvent.click(screen.getByRole("link", { name: /dashboard/i }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Discard unsaved changes?");

    fireEvent.click(screen.getByRole("button", { name: "Stay" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(router.state.location.pathname).toBe("/settings");
    expect((await nameInput()).value).toBe("Olive O.");

    fireEvent.click(screen.getByRole("link", { name: /dashboard/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Leave page" }));
    expect(await screen.findByRole("heading", { name: "Dashboard page" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/dashboard");
  });

  it("prompts on tab close only while there are unsaved changes", async () => {
    renderSettings();
    const input = await nameInput();
    expect(fireBeforeUnload().defaultPrevented).toBe(false);

    fireEvent.change(input, { target: { value: "Olive O." } });
    await waitFor(() => expect(saveButton()).toBeEnabled());
    expect(fireBeforeUnload().defaultPrevented).toBe(true);

    fireEvent.change(input, { target: { value: USER.displayName } });
    await waitFor(() => expect(saveButton()).toBeDisabled());
    expect(fireBeforeUnload().defaultPrevented).toBe(false);
  });

  it("does not warn after reverting the fields to their original values", async () => {
    const router = renderSettings();
    const input = await nameInput();
    fireEvent.change(input, { target: { value: "Olive O." } });
    await waitFor(() => expect(saveButton()).toBeEnabled());
    fireEvent.change(input, { target: { value: USER.displayName } });
    await waitFor(() => expect(saveButton()).toBeDisabled());

    fireEvent.click(screen.getByRole("link", { name: /dashboard/i }));
    expect(await screen.findByRole("heading", { name: "Dashboard page" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/dashboard");
  });

  it("does not warn after the changes are saved", async () => {
    const router = renderSettings();
    fireEvent.change(await nameInput(), { target: { value: "Olive O." } });
    await waitFor(() => expect(saveButton()).toBeEnabled());

    fireEvent.click(saveButton());
    expect(await screen.findByText("Profile updated successfully.")).toBeInTheDocument();
    expect(authApi.updateProfile).toHaveBeenCalledWith({
      displayName: "Olive O.",
      email: USER.email,
    });
    await waitFor(() => expect(saveButton()).toBeDisabled());
    expect(fireBeforeUnload().defaultPrevented).toBe(false);

    fireEvent.click(screen.getByRole("link", { name: /dashboard/i }));
    expect(await screen.findByRole("heading", { name: "Dashboard page" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/dashboard");
  });
});
