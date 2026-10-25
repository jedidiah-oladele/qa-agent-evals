import { CurrencyMismatchError, UnknownCurrencyError, ValidationError } from "./errors";
import { type RoundingMode, roundToInteger } from "./rounding";

export interface CurrencyInfo {
  readonly code: string;
  /** Digits after the decimal point: 2 for USD, 0 for JPY, 3 for KWD. */
  readonly exponent: number;
}

export const CURRENCIES: Readonly<Record<string, CurrencyInfo>> = Object.freeze({
  USD: { code: "USD", exponent: 2 },
  EUR: { code: "EUR", exponent: 2 },
  GBP: { code: "GBP", exponent: 2 },
  CHF: { code: "CHF", exponent: 2 },
  NGN: { code: "NGN", exponent: 2 },
  JPY: { code: "JPY", exponent: 0 },
  KWD: { code: "KWD", exponent: 3 },
});

export function currencyInfo(code: string): CurrencyInfo {
  const info = CURRENCIES[code];
  if (!info) {
    throw new UnknownCurrencyError(`unknown currency: ${code}`);
  }
  return info;
}

/** An amount in integer minor units (cents for USD, yen for JPY). */
export interface Money {
  readonly minor: number;
  readonly currency: string;
}

export function money(minor: number, currency: string): Money {
  currencyInfo(currency);
  if (!Number.isSafeInteger(minor)) {
    throw new ValidationError(`minor units must be a safe integer, got ${minor}`);
  }
  return Object.freeze({ minor: minor + 0, currency });
}

export function zero(currency: string): Money {
  return money(0, currency);
}

const DECIMAL = /^(-)?(\d+)(?:\.(\d+))?$/;

/** Parse a decimal string such as "12.34" exactly, without floating point. */
export function fromDecimal(text: string, currency: string): Money {
  const { exponent } = currencyInfo(currency);
  const match = DECIMAL.exec(text.trim());
  if (!match) {
    throw new ValidationError(`not a decimal amount: ${JSON.stringify(text)}`);
  }
  const [, sign, whole = "0", fraction = ""] = match;
  if (fraction.length > exponent) {
    throw new ValidationError(`${currency} allows ${exponent} decimal places, got ${JSON.stringify(text)}`);
  }
  const minor = Number(whole + fraction.padEnd(exponent, "0"));
  return money(sign ? -minor : minor, currency);
}

/** Format minor units back into a plain decimal string ("-0.05", "1200"). */
export function toDecimal(m: Money): string {
  const { exponent } = currencyInfo(m.currency);
  const digits = Math.abs(m.minor).toString().padStart(exponent + 1, "0");
  const sign = m.minor < 0 ? "-" : "";
  if (exponent === 0) {
    return sign + digits;
  }
  return `${sign}${digits.slice(0, -exponent)}.${digits.slice(-exponent)}`;
}

export function format(m: Money): string {
  return `${m.currency} ${toDecimal(m)}`;
}

function assertSame(a: Money, b: Money): void {
  if (a.currency !== b.currency) {
    throw new CurrencyMismatchError(a.currency, b.currency);
  }
}

export function add(a: Money, b: Money): Money {
  assertSame(a, b);
  return money(a.minor + b.minor, a.currency);
}

export function subtract(a: Money, b: Money): Money {
  assertSame(a, b);
  return money(a.minor - b.minor, a.currency);
}

export function negate(m: Money): Money {
  return money(-m.minor, m.currency);
}

export function sum(values: readonly Money[], currency: string): Money {
  return values.reduce((acc, v) => add(acc, v), zero(currency));
}

export function compare(a: Money, b: Money): -1 | 0 | 1 {
  assertSame(a, b);
  return a.minor === b.minor ? 0 : a.minor < b.minor ? -1 : 1;
}

export function equals(a: Money, b: Money): boolean {
  return a.currency === b.currency && a.minor === b.minor;
}

export function isZero(m: Money): boolean {
  return m.minor === 0;
}

/** Multiply by a factor (quantity, rate, percentage) and round to minor units. */
export function multiply(m: Money, factor: number, mode: RoundingMode = "half-up"): Money {
  return money(roundToInteger(m.minor * factor, mode), m.currency);
}

/**
 * Split `m` across `ratios` so the parts add up exactly to `m`.
 *
 * Each part gets the floor of its exact share; the leftover minor units go to
 * the parts with the largest fractional remainders, earliest first on ties.
 */
export function allocate(m: Money, ratios: readonly number[]): Money[] {
  if (ratios.length === 0) {
    throw new ValidationError("allocate needs at least one ratio");
  }
  if (ratios.some((r) => r < 0 || !Number.isFinite(r))) {
    throw new ValidationError("ratios must be finite and non-negative");
  }
  const total = ratios.reduce((a, b) => a + b, 0);
  if (total <= 0) {
    throw new ValidationError("at least one ratio must be positive");
  }
  const sign = m.minor < 0 ? -1 : 1;
  const units = Math.abs(m.minor);
  const exact = ratios.map((r) => (units * r) / total);
  const parts = exact.map((x) => Math.floor(x + 1e-9));
  let leftover = units - parts.reduce((a, b) => a + b, 0);
  const order = exact
    .map((x, i) => ({ i, rem: x - Math.floor(x + 1e-9) }))
    .sort((a, b) => b.rem - a.rem || a.i - b.i);
  for (const { i } of order) {
    if (leftover <= 0) break;
    parts[i] = (parts[i] ?? 0) + 1;
    leftover -= 1;
  }
  return parts.map((p) => money(sign * p, m.currency));
}
