import { http, HttpResponse } from "msw";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import BillingPlansPage from "./plans-page";
import { billingServer } from "./test-setup";

function renderPage() {
  return render(
    <MemoryRouter>
      <BillingPlansPage />
    </MemoryRouter>
  );
}

describe("Billing plans", () => {
  it("renders plans from the billing service", async () => {
    billingServer.use(
      http.get("http://localhost:8097/api/plans", () =>
        HttpResponse.json([
          {
            plan_id: "one",
            code: "STARTER",
            tier: "starter",
            monthly_fee: "49.00",
            included_units: 100,
            overage_rate: "0.055000",
          },
        ])
      )
    );
    renderPage();
    expect(await screen.findByText("STARTER")).toBeInTheDocument();
    expect(screen.getByText(/49\.00/)).toBeInTheDocument();
  });

  it("shows and dismisses a retryable error", async () => {
    billingServer.use(
      http.get("http://localhost:8097/api/plans", () =>
        HttpResponse.json({ message: "nope" }, { status: 503 })
      )
    );
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Plans could not be loaded.");
    fireEvent.click(screen.getByRole("button", { name: "Dismiss error" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });
});
