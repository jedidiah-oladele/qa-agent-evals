import { describe, expect, it } from "vitest";
import { type Interval, planChangeAdjustment } from "../src/index";
import { ValidationError } from "../src/errors";
import { type Money, money } from "../src/money";

function change(oldPrice: Money, newPrice: Money, anchor: string, interval: Interval, changeOn: string) {
  return planChangeAdjustment({ oldPrice, newPrice, anchor, interval, changeOn });
}

describe("planChangeAdjustment edge cases", () => {
  it("nets the rounded credit and charge, so reversing a change negates it exactly", () => {
    // 10 of 30 days remain: 1001/3 = 333.67 -> 334 credit, 2002/3 = 667.33 -> 667 charge.
    const up = change(money(1001, "USD"), money(2002, "USD"), "2026-01-01", "monthly", "2026-04-21");
    expect(up.credit.minor).toBe(334);
    expect(up.charge.minor).toBe(667);
    expect(up.net.minor).toBe(333);
    const down = change(money(2002, "USD"), money(1001, "USD"), "2026-01-01", "monthly", "2026-04-21");
    expect(down.net.minor).toBe(-333);
  });

  it("uses the billing period from the anchor, not the calendar month", () => {
    // Anchor on the 15th: the period is Feb 15 - Mar 15 (28 days); 5 days remain.
    const result = change(money(2800, "EUR"), money(5600, "EUR"), "2026-01-15", "monthly", "2026-03-10");
    expect(result.period).toEqual({ start: "2026-02-15", end: "2026-03-15" });
    expect(result.credit.minor).toBe(500);
    expect(result.charge.minor).toBe(1000);
    expect(result.net.minor).toBe(500);
  });

  it("keeps month-end anchors from drifting across a leap February", () => {
    // Anchor Jan 31: periods are Feb 29 - Mar 31 (31 days); 30 days remain from Mar 1.
    const result = change(money(3100, "USD"), money(6200, "USD"), "2024-01-31", "monthly", "2024-03-01");
    expect(result.period).toEqual({ start: "2024-02-29", end: "2024-03-31" });
    expect(result.credit.minor).toBe(3000);
    expect(result.charge.minor).toBe(6000);
  });

  it("supports quarterly plans", () => {
    // May 10 - Aug 10 is 92 days; 40 remain from Jul 1.
    const result = change(money(9200, "GBP"), money(18_400, "GBP"), "2026-02-10", "quarterly", "2026-07-01");
    expect(result.period).toEqual({ start: "2026-05-10", end: "2026-08-10" });
    expect(result.credit.minor).toBe(4000);
    expect(result.charge.minor).toBe(8000);
  });

  it("swaps the full price when changing on the anchor day itself", () => {
    const result = change(money(1500, "USD"), money(4500, "USD"), "2026-03-01", "monthly", "2026-03-01");
    expect(result.period).toEqual({ start: "2026-03-01", end: "2026-04-01" });
    expect(result.credit.minor).toBe(1500);
    expect(result.charge.minor).toBe(4500);
    expect(result.net.minor).toBe(3000);
  });

  it("prorates a single remaining day on the last day of a period", () => {
    const result = change(money(3000, "USD"), money(6000, "USD"), "2026-01-01", "monthly", "2026-04-30");
    expect(result.period.end).toBe("2026-05-01");
    expect(result.credit.minor).toBe(100);
    expect(result.charge.minor).toBe(200);
  });

  it("refunds the unused time when downgrading to a free plan", () => {
    const result = change(money(6000, "USD"), money(0, "USD"), "2026-01-01", "monthly", "2026-04-21");
    expect(result.charge.minor).toBe(0);
    expect(result.net.minor).toBe(-2000);
    expect(result.net.currency).toBe("USD");
  });

  it("handles zero-decimal currencies", () => {
    const result = change(money(1000, "JPY"), money(2500, "JPY"), "2026-01-01", "monthly", "2026-04-21");
    expect(result.credit).toEqual({ minor: 333, currency: "JPY" });
    expect(result.charge).toEqual({ minor: 833, currency: "JPY" });
    expect(result.net).toEqual({ minor: 500, currency: "JPY" });
  });

  it("rejects a change before the billing anchor", () => {
    expect(() => change(money(100, "USD"), money(200, "USD"), "2026-05-01", "monthly", "2026-04-30")).toThrow(
      ValidationError,
    );
  });
});
