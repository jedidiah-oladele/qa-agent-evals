import { describe, expect, it } from "vitest";
import { CurrencyMismatchError, UnknownCurrencyError, ValidationError } from "../src/errors";
import {
  add,
  allocate,
  compare,
  equals,
  format,
  fromDecimal,
  isZero,
  money,
  multiply,
  negate,
  subtract,
  sum,
  toDecimal,
  zero,
} from "../src/money";

describe("money construction", () => {
  it("stores integer minor units", () => {
    expect(money(1234, "USD")).toEqual({ minor: 1234, currency: "USD" });
  });

  it("rejects unknown currencies and fractional minor units", () => {
    expect(() => money(1, "XYZ")).toThrow(UnknownCurrencyError);
    expect(() => money(1.5, "USD")).toThrow(ValidationError);
  });

  it("is frozen", () => {
    expect(Object.isFrozen(money(1, "USD"))).toBe(true);
  });
});

describe("fromDecimal / toDecimal", () => {
  it.each([
    ["12.34", "USD", 1234],
    ["12.3", "USD", 1230],
    ["12", "USD", 1200],
    ["-0.05", "USD", -5],
    ["1200", "JPY", 1200],
    ["1.234", "KWD", 1234],
    [" 7.10 ", "EUR", 710],
  ])("parses %s %s", (text, currency, minor) => {
    expect(fromDecimal(text, currency).minor).toBe(minor);
  });

  it("rejects too many decimals and junk", () => {
    expect(() => fromDecimal("1.234", "USD")).toThrow(ValidationError);
    expect(() => fromDecimal("1.5", "JPY")).toThrow(ValidationError);
    expect(() => fromDecimal("1e3", "USD")).toThrow(ValidationError);
    expect(() => fromDecimal("", "USD")).toThrow(ValidationError);
  });

  it.each([
    [1234, "USD", "12.34"],
    [5, "USD", "0.05"],
    [-5, "USD", "-0.05"],
    [1200, "JPY", "1200"],
    [7, "KWD", "0.007"],
  ])("formats %d %s as %s", (minor, currency, text) => {
    expect(toDecimal(money(minor, currency))).toBe(text);
  });

  it("format includes the currency code", () => {
    expect(format(money(199, "GBP"))).toBe("GBP 1.99");
  });
});

describe("arithmetic", () => {
  it("adds, subtracts, negates and sums", () => {
    const a = money(150, "USD");
    const b = money(275, "USD");
    expect(add(a, b).minor).toBe(425);
    expect(subtract(a, b).minor).toBe(-125);
    expect(negate(a).minor).toBe(-150);
    expect(sum([a, b, a], "USD").minor).toBe(575);
    expect(sum([], "EUR")).toEqual(zero("EUR"));
  });

  it("refuses to mix currencies", () => {
    expect(() => add(money(1, "USD"), money(1, "EUR"))).toThrow(CurrencyMismatchError);
    expect(() => compare(money(1, "USD"), money(1, "EUR"))).toThrow(CurrencyMismatchError);
  });

  it("compares and checks equality", () => {
    expect(compare(money(1, "USD"), money(2, "USD"))).toBe(-1);
    expect(compare(money(2, "USD"), money(2, "USD"))).toBe(0);
    expect(equals(money(2, "USD"), money(2, "EUR"))).toBe(false);
    expect(isZero(zero("JPY"))).toBe(true);
  });

  it("multiplies with rounding", () => {
    expect(multiply(money(999, "USD"), 3).minor).toBe(2997);
    expect(multiply(money(1999, "USD"), 0.075).minor).toBe(150); // 149.925
    expect(multiply(money(250, "USD"), 0.5, "half-even").minor).toBe(125);
    expect(multiply(money(5, "USD"), 0.5, "half-even").minor).toBe(2);
    expect(multiply(money(5, "USD"), 0.5).minor).toBe(3);
  });
});

describe("allocate", () => {
  it("splits evenly when possible", () => {
    expect(allocate(money(900, "USD"), [1, 1, 1]).map((m) => m.minor)).toEqual([300, 300, 300]);
  });

  it("hands leftover units to the largest remainders, earliest first", () => {
    expect(allocate(money(1000, "USD"), [1, 1, 1]).map((m) => m.minor)).toEqual([334, 333, 333]);
    expect(allocate(money(100, "USD"), [1, 2]).map((m) => m.minor)).toEqual([33, 67]);
  });

  it("always sums to the original amount", () => {
    const parts = allocate(money(10_001, "USD"), [3.3, 1.7, 5, 0.01]);
    expect(parts.reduce((a, p) => a + p.minor, 0)).toBe(10_001);
  });

  it("handles negative amounts and zero ratios", () => {
    expect(allocate(money(-100, "USD"), [1, 0, 2]).map((m) => m.minor)).toEqual([-33, 0, -67]);
  });

  it("validates ratios", () => {
    expect(() => allocate(money(1, "USD"), [])).toThrow(ValidationError);
    expect(() => allocate(money(1, "USD"), [0, 0])).toThrow(ValidationError);
    expect(() => allocate(money(1, "USD"), [1, -1])).toThrow(ValidationError);
  });
});
