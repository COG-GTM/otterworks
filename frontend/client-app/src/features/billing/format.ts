export function formatMoney(value: string) {
  const amount = Number(value);
  return Number.isFinite(amount) ? amount.toFixed(2) : value;
}

export const DEFAULT_PERIOD = { period_start: "2026-02-01", period_end: "2026-02-28" };
export const DEFAULT_AS_OF = "2026-02-28";
