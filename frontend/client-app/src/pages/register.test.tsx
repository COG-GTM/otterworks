import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import RegisterPage from "./register";

function renderPage() {
  return render(
    <MemoryRouter>
      <RegisterPage />
    </MemoryRouter>
  );
}

function typePassword(value: string) {
  fireEvent.input(screen.getByLabelText("Password"), { target: { value } });
}

describe("Register page password strength meter", () => {
  it("is hidden while the password field is empty", () => {
    renderPage();
    expect(screen.queryByRole("meter", { name: "Password strength" })).not.toBeInTheDocument();
  });

  it("updates as the user types and hides again when cleared", async () => {
    renderPage();

    typePassword("password");
    expect(await screen.findByText("Password strength: Weak")).toBeInTheDocument();

    typePassword("Password1");
    expect(await screen.findByText("Password strength: Fair")).toBeInTheDocument();

    typePassword("Password1!");
    expect(await screen.findByText("Password strength: Strong")).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Password strength" })).toHaveAttribute(
      "aria-valuetext",
      "Strong"
    );

    typePassword("");
    await screen.findByLabelText("Password");
    expect(screen.queryByRole("meter", { name: "Password strength" })).not.toBeInTheDocument();
  });

  it("keeps the 8-character minimum on submit", async () => {
    renderPage();
    typePassword("Ab1!");
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(
      await screen.findByText("Password must be at least 8 characters")
    ).toBeInTheDocument();
  });
});
