import { describe, expect, it } from "vitest";
import { nthPeriod, planChangeAdjustment, prorate } from "../src/billing";
import { money } from "../src/money";

const april = { start: "2026-04-01", end: "2026-05-01" }; // 30 days
const price = money(3_000, "USD");

describe("prorate for subscriptions that started before the period", () => {
  it("charges only the days inside the period when cancelling early in it", () => {
    expect(prorate(price, april, "2026-03-25", "2026-04-03").minor).toBe(200);
  });

  it("charges a long-running subscription by its active days in the final period", () => {
    expect(prorate(price, april, "2025-11-01", "2026-04-11").minor).toBe(1_000);
  });

  it("charges nothing when the subscription ended before the period", () => {
    expect(prorate(price, april, "2026-03-01", "2026-03-20").minor).toBe(0);
  });

  it("charges nothing when the subscription ended on the first day of the period", () => {
    expect(prorate(price, april, "2026-03-10", "2026-04-01").minor).toBe(0);
  });

  it("clamps yearly periods the same way", () => {
    const year = nthPeriod("2026-01-01", 0, "yearly"); // 365 days
    expect(prorate(money(36_500, "USD"), year, "2025-06-01", "2026-01-06").minor).toBe(500);
  });
});

describe("prorate guards", () => {
  it("charges by active days when the subscription starts mid-period and outlives it", () => {
    expect(prorate(price, april, "2026-04-11", "2026-07-01").minor).toBe(2_000);
  });

  it("charges the full price when active across the whole period", () => {
    expect(prorate(price, april, "2025-01-01", "2027-01-01")).toEqual(price);
  });

  it("charges nothing for a subscription starting after the period", () => {
    expect(prorate(price, april, "2026-05-01", "2026-05-20").minor).toBe(0);
    expect(prorate(price, april, "2026-06-01", "2026-07-01").minor).toBe(0);
  });

  it("keeps half-up rounding", () => {
    const period = { start: "2026-01-01", end: "2026-01-04" };
    expect(prorate(money(1_000, "USD"), period, "2026-01-02", "2026-02-01").minor).toBe(667);
    expect(prorate(money(1_000, "USD"), period, "2026-01-03", "2026-02-01").minor).toBe(333);
  });

  it("leaves plan-change adjustments unchanged", () => {
    const result = planChangeAdjustment({
      oldPrice: money(3_000, "USD"),
      newPrice: money(6_000, "USD"),
      anchor: "2026-01-01",
      interval: "monthly",
      changeOn: "2026-04-21",
    });
    expect([result.credit.minor, result.charge.minor, result.net.minor]).toEqual([1_000, 2_000, 1_000]);
  });
});
