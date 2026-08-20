import { http, HttpResponse, delay } from "msw";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import BillingPlansPage from "./plans-page";
import { billingServer } from "../../test-setup";

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
      http.get("http://localhost:3000/billing-api/api/plans", () =>
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
    let attempts = 0;
    billingServer.use(
      http.get("http://localhost:3000/billing-api/api/plans", () => {
        attempts += 1;
        return attempts === 1
          ? HttpResponse.json({ message: "nope" }, { status: 503 })
          : HttpResponse.json([
              {
                plan_id: "two",
                code: "GROWTH",
                tier: "growth",
                monthly_fee: "149.00",
                included_units: 500,
                overage_rate: "0.045000",
              },
            ]);
      })
    );
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Plans could not be loaded.");
    expect(screen.queryByText("No plans are available.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("GROWTH")).toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it("shows and dismisses a retryable error", async () => {
    billingServer.use(
      http.get("http://localhost:3000/billing-api/api/plans", () =>
        HttpResponse.json({ message: "nope" }, { status: 503 })
      )
    );
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Plans could not be loaded.");
    fireEvent.click(screen.getByRole("button", { name: "Dismiss error" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("ignores an earlier failure when Retry has a newer successful request", async () => {
    let attempts = 0;
    billingServer.use(
      http.get("http://localhost:3000/billing-api/api/plans", async () => {
        attempts += 1;
        if (attempts === 1) {
          await delay(100);
          return HttpResponse.json({ message: "nope" }, { status: 503 });
        }
        return HttpResponse.json([
          {
            plan_id: "three",
            code: "SCALE",
            tier: "scale",
            monthly_fee: "499.00",
            included_units: 2000,
            overage_rate: "0.035000",
          },
        ]);
      }),
    );
    renderPage();
    await waitFor(() => expect(attempts).toBe(1));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("SCALE")).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("SCALE")).toBeInTheDocument();
  });
});
