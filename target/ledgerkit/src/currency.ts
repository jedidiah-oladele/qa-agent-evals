import { RateNotFoundError, ValidationError } from "./errors";
import { type Money, currencyInfo, money } from "./money";
import { type RoundingMode, roundToInteger } from "./rounding";

/**
 * Exchange rates quoted against a base currency: `rates[X]` is how many units
 * of X one unit of `base` buys. Conversions between two non-base currencies
 * go through the base (a cross rate).
 */
export class RateTable {
  private readonly rates: Map<string, number>;

  constructor(
    readonly base: string,
    rates: Readonly<Record<string, number>>,
    readonly asOf: Date,
  ) {
    currencyInfo(base);
    this.rates = new Map();
    for (const [code, rate] of Object.entries(rates)) {
      currencyInfo(code);
      if (!(rate > 0) || !Number.isFinite(rate)) {
        throw new ValidationError(`rate for ${code} must be a positive number, got ${rate}`);
      }
      this.rates.set(code, rate);
    }
    this.rates.set(base, 1);
  }

  has(code: string): boolean {
    return this.rates.has(code);
  }

  private quote(code: string): number {
    const rate = this.rates.get(code);
    if (rate === undefined) {
      throw new RateNotFoundError(`no ${this.base}->${code} rate`);
    }
    return rate;
  }

  /** Units of `to` per one unit of `from`. */
  rate(from: string, to: string): number {
    if (from === to) return 1;
    return this.quote(to) / this.quote(from);
  }

  /** Convert `amount` into `to`, rounding once at the end. */
  convert(amount: Money, to: string, mode: RoundingMode = "half-up"): Money {
    if (amount.currency === to) return amount;
    const fromExp = currencyInfo(amount.currency).exponent;
    const toExp = currencyInfo(to).exponent;
    const value = amount.minor * this.rate(amount.currency, to) * 10 ** (toExp - fromExp);
    return money(roundToInteger(value, mode), to);
  }

  /** True when the rates are older than `maxAgeMs` at time `now`. */
  isStale(now: Date, maxAgeMs: number): boolean {
    return now.getTime() - this.asOf.getTime() > maxAgeMs;
  }
}
