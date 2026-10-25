import { describe, expect, it } from "vitest";
import { RateTable } from "../src/currency";
import { RateNotFoundError, UnknownCurrencyError, ValidationError } from "../src/errors";
import { money } from "../src/money";

const asOf = new Date("2026-10-01T00:00:00Z");
const table = new RateTable("USD", { EUR: 0.92, GBP: 0.79, JPY: 151.4, KWD: 0.307 }, asOf);

describe("RateTable.rate", () => {
  it("is 1 for the same currency and reads direct quotes", () => {
    expect(table.rate("EUR", "EUR")).toBe(1);
    expect(table.rate("USD", "EUR")).toBe(0.92);
  });

  it("inverts quotes into the base currency", () => {
    expect(table.rate("EUR", "USD")).toBeCloseTo(1 / 0.92, 12);
  });

  it("computes cross rates through the base", () => {
    expect(table.rate("EUR", "GBP")).toBeCloseTo(0.79 / 0.92, 12);
  });

  it("throws for missing rates", () => {
    expect(() => table.rate("USD", "CHF")).toThrow(RateNotFoundError);
  });
});

describe("RateTable.convert", () => {
  it("converts base to quote currency", () => {
    expect(table.convert(money(10_000, "USD"), "EUR")).toEqual(money(9_200, "EUR"));
  });

  it("handles different exponents", () => {
    expect(table.convert(money(1_000, "USD"), "JPY")).toEqual(money(1_514, "JPY"));
    expect(table.convert(money(1_514, "JPY"), "USD")).toEqual(money(1_000, "USD"));
    expect(table.convert(money(1_000, "USD"), "KWD")).toEqual(money(3_070, "KWD"));
  });

  it("rounds once, at the end", () => {
    // 1.00 EUR -> GBP: 100 * 0.79 / 0.92 = 85.869... -> 86
    expect(table.convert(money(100, "EUR"), "GBP").minor).toBe(86);
    expect(table.convert(money(100, "EUR"), "GBP", "floor").minor).toBe(85);
  });

  it("returns the same amount for same-currency conversion", () => {
    const m = money(123, "EUR");
    expect(table.convert(m, "EUR")).toBe(m);
  });
});

describe("RateTable validation and staleness", () => {
  it("rejects non-positive rates and unknown codes", () => {
    expect(() => new RateTable("USD", { EUR: 0 }, asOf)).toThrow(ValidationError);
    expect(() => new RateTable("USD", { EUR: Number.NaN }, asOf)).toThrow(ValidationError);
    expect(() => new RateTable("USD", { XYZ: 1 }, asOf)).toThrow(UnknownCurrencyError);
  });

  it("knows the base currency", () => {
    expect(table.has("USD")).toBe(true);
    expect(table.has("CHF")).toBe(false);
  });

  it("reports staleness strictly after the max age", () => {
    const day = 86_400_000;
    expect(table.isStale(new Date(asOf.getTime() + day), day)).toBe(false);
    expect(table.isStale(new Date(asOf.getTime() + day + 1), day)).toBe(true);
  });
});
