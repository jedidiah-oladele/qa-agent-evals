import { describe, expect, it } from "vitest";
import { billingPeriods, nthPeriod, periodContaining, periodDays, prorate } from "../src/billing";
import { ValidationError } from "../src/errors";
import { money } from "../src/money";

describe("periods", () => {
  it("computes the nth monthly period from the anchor", () => {
    expect(nthPeriod("2026-01-15", 0, "monthly")).toEqual({ start: "2026-01-15", end: "2026-02-15" });
    expect(nthPeriod("2026-01-15", 2, "monthly")).toEqual({ start: "2026-03-15", end: "2026-04-15" });
  });

  it("does not drift for month-end anchors", () => {
    const starts = billingPeriods("2026-01-31", "2026-06-01", "monthly").map((p) => p.start);
    expect(starts).toEqual(["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30", "2026-05-31"]);
  });

  it("supports quarterly and yearly intervals", () => {
    expect(nthPeriod("2026-02-01", 1, "quarterly")).toEqual({ start: "2026-05-01", end: "2026-08-01" });
    expect(nthPeriod("2024-02-29", 1, "yearly")).toEqual({ start: "2025-02-28", end: "2026-02-28" });
  });

  it("billingPeriods stops before `until`", () => {
    expect(billingPeriods("2026-01-01", "2026-03-01", "monthly")).toHaveLength(2);
    expect(billingPeriods("2026-01-01", "2026-03-02", "monthly")).toHaveLength(3);
    expect(billingPeriods("2026-01-01", "2026-01-01", "monthly")).toHaveLength(0);
  });

  it("finds the period containing a date", () => {
    expect(periodContaining("2026-01-31", "2026-03-30", "monthly")).toEqual({
      start: "2026-02-28",
      end: "2026-03-31",
    });
    expect(periodContaining("2026-01-31", "2026-03-31", "monthly").start).toBe("2026-03-31");
    expect(periodContaining("2026-01-01", "2026-01-01", "yearly").end).toBe("2027-01-01");
    expect(periodContaining("2020-01-10", "2026-07-09", "monthly")).toEqual({
      start: "2026-06-10",
      end: "2026-07-10",
    });
  });

  it("rejects dates before the anchor", () => {
    expect(() => periodContaining("2026-01-10", "2026-01-09", "monthly")).toThrow(ValidationError);
  });

  it("counts period days with exclusive end", () => {
    expect(periodDays({ start: "2026-02-01", end: "2026-03-01" })).toBe(28);
  });
});

describe("prorate", () => {
  const april = { start: "2026-04-01", end: "2026-05-01" }; // 30 days
  const price = money(3000, "USD");

  it("charges in full when active the whole period", () => {
    expect(prorate(price, april, "2026-03-01", "2026-06-01")).toEqual(price);
  });

  it("charges by active days with exclusive end", () => {
    expect(prorate(price, april, "2026-04-11", "2026-05-01").minor).toBe(2000);
    expect(prorate(price, april, "2026-04-01", "2026-04-02").minor).toBe(100);
  });

  it("charges nothing without overlap", () => {
    expect(prorate(price, april, "2026-05-01", "2026-06-01").minor).toBe(0);
    expect(prorate(price, april, "2026-04-10", "2026-04-10").minor).toBe(0);
  });

  it("rounds half-up", () => {
    // 1000 * 1/3 = 333.33 -> 333 ; 1000 * 2/3 = 666.67 -> 667
    const period = { start: "2026-01-01", end: "2026-01-04" };
    expect(prorate(money(1000, "USD"), period, "2026-01-01", "2026-01-02").minor).toBe(333);
    expect(prorate(money(1000, "USD"), period, "2026-01-01", "2026-01-03").minor).toBe(667);
  });

  it("uses the real length of February", () => {
    const feb = { start: "2028-02-01", end: "2028-03-01" }; // leap year, 29 days
    expect(prorate(money(2900, "USD"), feb, "2028-02-15", "2028-03-01").minor).toBe(1500);
  });
});
