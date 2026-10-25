import { describe, expect, it } from "vitest";
import { roundToInteger } from "../src/rounding";

describe("roundToInteger", () => {
  it.each([
    [2.5, 3],
    [-2.5, -3],
    [2.4999, 2],
    [0.5, 1],
    [-0.4, 0],
  ])("half-up %d -> %d", (input, expected) => {
    expect(roundToInteger(input, "half-up")).toBe(expected);
  });

  it.each([
    [2.5, 2],
    [3.5, 4],
    [-2.5, -2],
    [2.6, 3],
  ])("half-even %d -> %d", (input, expected) => {
    expect(roundToInteger(input, "half-even")).toBe(expected);
  });

  it("floor and ceil", () => {
    expect(roundToInteger(2.7, "floor")).toBe(2);
    expect(roundToInteger(-2.2, "floor")).toBe(-3);
    expect(roundToInteger(2.2, "ceil")).toBe(3);
  });

  it("is not fooled by binary floating point noise", () => {
    expect(1.005 * 100).not.toBe(100.5);
    expect(roundToInteger(1.005 * 100)).toBe(101);
    expect(roundToInteger(0.285 * 100)).toBe(29);
  });

  it("never returns negative zero", () => {
    expect(Object.is(roundToInteger(-0.2), 0)).toBe(true);
  });

  it("rejects non-finite values", () => {
    expect(() => roundToInteger(Number.NaN)).toThrow(RangeError);
    expect(() => roundToInteger(Number.POSITIVE_INFINITY)).toThrow(RangeError);
  });
});
