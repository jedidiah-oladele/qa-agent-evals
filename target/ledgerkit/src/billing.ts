import { CurrencyMismatchError, ValidationError } from "./errors";
import { type ISODate, addMonths, compareDates, daysBetween, maxDate, minDate } from "./dates";
import { type Money, multiply, subtract, zero } from "./money";

export type Interval = "monthly" | "quarterly" | "yearly";

const MONTHS: Record<Interval, number> = { monthly: 1, quarterly: 3, yearly: 12 };

/** A billing period covering `start` up to but not including `end`. */
export interface Period {
  readonly start: ISODate;
  readonly end: ISODate;
}

export function periodDays(period: Period): number {
  return daysBetween(period.start, period.end);
}

/**
 * The `index`-th period after `anchor`. Every boundary is computed from the
 * anchor (not from the previous boundary) so month-end anchors do not drift:
 * an anchor of Jan 31 gives Feb 28, Mar 31, Apr 30, ...
 */
export function nthPeriod(anchor: ISODate, index: number, interval: Interval): Period {
  const step = MONTHS[interval];
  return { start: addMonths(anchor, index * step), end: addMonths(anchor, (index + 1) * step) };
}

/** Every period from `anchor` whose start is before `until`. */
export function billingPeriods(anchor: ISODate, until: ISODate, interval: Interval): Period[] {
  const periods: Period[] = [];
  for (let i = 0; ; i++) {
    const period = nthPeriod(anchor, i, interval);
    if (compareDates(period.start, until) >= 0) break;
    periods.push(period);
  }
  return periods;
}

/** The period (counted from `anchor`) that contains `date`. */
export function periodContaining(anchor: ISODate, date: ISODate, interval: Interval): Period {
  if (compareDates(date, anchor) < 0) {
    throw new ValidationError(`${date} is before the billing anchor ${anchor}`);
  }
  const months = MONTHS[interval];
  let index = Math.max(0, Math.floor(daysBetween(anchor, date) / (31 * months)) - 1);
  for (;;) {
    const period = nthPeriod(anchor, index, interval);
    if (compareDates(date, period.end) < 0) return period;
    index++;
  }
}

/**
 * Charge for the part of `period` during which a subscription was active.
 * `activeFrom` is inclusive and `activeTo` exclusive. The charge is
 * `price * overlapDays / periodDays`, rounded half-up to minor units.
 */
export function prorate(price: Money, period: Period, activeFrom: ISODate, activeTo: ISODate): Money {
  const from = maxDate(period.start, activeFrom);
  const to = minDate(period.end, activeTo);
  const overlap = daysBetween(from, to);
  if (overlap <= 0) return zero(price.currency);
  const total = periodDays(period);
  if (overlap >= total) return price;
  return multiply(price, overlap / total);
}

export interface PlanChange {
  readonly oldPrice: Money;
  readonly newPrice: Money;
  readonly anchor: ISODate;
  readonly interval: Interval;
  /** First day on the new plan. */
  readonly changeOn: ISODate;
}

export interface Adjustment {
  readonly period: Period;
  /** Unused time on the old plan, returned to the customer. */
  readonly credit: Money;
  /** Remaining time on the new plan. */
  readonly charge: Money;
  /** `charge - credit`; negative means the customer is owed money. */
  readonly net: Money;
}

/**
 * Mid-period plan change: credit the unused part of the old plan and charge
 * the new plan for the rest of the same period. Both sides use the same day
 * count so an upgrade and an immediate downgrade cancel out.
 */
export function planChangeAdjustment(change: PlanChange): Adjustment {
  const { oldPrice, newPrice, anchor, interval, changeOn } = change;
  if (oldPrice.currency !== newPrice.currency) {
    throw new CurrencyMismatchError(oldPrice.currency, newPrice.currency);
  }
  const period = periodContaining(anchor, changeOn, interval);
  const credit = prorate(oldPrice, period, changeOn, period.end);
  const charge = prorate(newPrice, period, changeOn, period.end);
  return { period, credit, charge, net: subtract(charge, credit) };
}
