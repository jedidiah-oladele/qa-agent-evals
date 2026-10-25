import { describe, expect, it } from "vitest";
import { planChangeAdjustment } from "../src/billing";
import { CurrencyMismatchError } from "../src/errors";
import { money } from "../src/money";

describe("planChangeAdjustment", () => {
  it("credits unused old plan and charges the new plan for the rest of the period", () => {
    const result = planChangeAdjustment({
      oldPrice: money(3000, "USD"),
      newPrice: money(6000, "USD"),
      anchor: "2026-01-01",
      interval: "monthly",
      changeOn: "2026-04-21", // 10 of 30 April days remain
    });
    expect(result.period).toEqual({ start: "2026-04-01", end: "2026-05-01" });
    expect(result.credit.minor).toBe(1000);
    expect(result.charge.minor).toBe(2000);
    expect(result.net.minor).toBe(1000);
  });

  it("gives a negative net for downgrades", () => {
    const result = planChangeAdjustment({
      oldPrice: money(6000, "USD"),
      newPrice: money(3000, "USD"),
      anchor: "2026-01-01",
      interval: "monthly",
      changeOn: "2026-04-21",
    });
    expect(result.net.minor).toBe(-1000);
  });

  it("changing on the first day of a period swaps the full price", () => {
    const result = planChangeAdjustment({
      oldPrice: money(1000, "EUR"),
      newPrice: money(2500, "EUR"),
      anchor: "2026-01-31",
      interval: "monthly",
      changeOn: "2026-02-28",
    });
    expect(result.period.start).toBe("2026-02-28");
    expect(result.credit.minor).toBe(1000);
    expect(result.charge.minor).toBe(2500);
  });

  it("works for yearly plans", () => {
    const result = planChangeAdjustment({
      oldPrice: money(36500, "USD"),
      newPrice: money(73000, "USD"),
      anchor: "2025-07-01",
      interval: "yearly",
      changeOn: "2026-06-26", // 5 of 365 days remain
    });
    expect(result.credit.minor).toBe(500);
    expect(result.charge.minor).toBe(1000);
  });

  it("rejects mixed currencies", () => {
    expect(() =>
      planChangeAdjustment({
        oldPrice: money(1, "USD"),
        newPrice: money(1, "EUR"),
        anchor: "2026-01-01",
        interval: "monthly",
        changeOn: "2026-01-05",
      }),
    ).toThrow(CurrencyMismatchError);
  });
});
