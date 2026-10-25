import { describe, expect, it } from "vitest";
import { CURRENCIES, format, fromDecimal, money, toDecimal, zero } from "../src/money";

describe("toDecimal for zero-decimal currencies", () => {
  it("formats small yen amounts without padding", () => {
    expect(toDecimal(money(50, "JPY"))).toBe("50");
    expect(toDecimal(money(5, "JPY"))).toBe("5");
    expect(toDecimal(money(-75, "JPY"))).toBe("-75");
  });

  it("formats zero yen as a single digit", () => {
    expect(toDecimal(zero("JPY"))).toBe("0");
  });
});

describe("toDecimal for three-decimal currencies", () => {
  it("keeps the leading zero for dinar amounts below one", () => {
    expect(toDecimal(money(250, "KWD"))).toBe("0.250");
    expect(toDecimal(money(7, "KWD"))).toBe("0.007");
    expect(toDecimal(money(-75, "KWD"))).toBe("-0.075");
  });

  it("formats zero dinars with three decimals", () => {
    expect(toDecimal(zero("KWD"))).toBe("0.000");
  });
});

describe("format across exponents", () => {
  it("prefixes the currency code to a well-formed amount", () => {
    expect(format(money(480, "JPY"))).toBe("JPY 480");
    expect(format(money(30, "JPY"))).toBe("JPY 30");
    expect(format(money(1, "KWD"))).toBe("KWD 0.001");
    expect(format(money(-990, "KWD"))).toBe("KWD -0.990");
  });

  it("round-trips through fromDecimal for every configured currency", () => {
    for (const code of Object.keys(CURRENCIES)) {
      for (const minor of [0, 1, 9, 10, 99, 100, 101, 999, 1000, 123_457, -1, -42, -1001]) {
        const m = money(minor, code);
        expect(fromDecimal(toDecimal(m), code)).toEqual(m);
      }
    }
  });
});

describe("toDecimal guards", () => {
  it("still formats two-decimal currencies", () => {
    expect(toDecimal(money(5, "USD"))).toBe("0.05");
    expect(toDecimal(money(0, "EUR"))).toBe("0.00");
    expect(toDecimal(money(-1_999, "GBP"))).toBe("-19.99");
    expect(toDecimal(money(120_000, "NGN"))).toBe("1200.00");
  });

  it("is exact for very large amounts", () => {
    expect(toDecimal(money(9_007_199_254_740_991, "KWD"))).toBe("9007199254740.991");
    expect(toDecimal(money(7_205_759_403_792_793, "USD"))).toBe("72057594037927.93");
    expect(toDecimal(money(9_007_199_254_740_991, "JPY"))).toBe("9007199254740991");
  });
});
