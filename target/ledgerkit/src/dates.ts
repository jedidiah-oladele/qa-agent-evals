import { ValidationError } from "./errors";

/** A calendar date with no time or zone, written "YYYY-MM-DD". */
export type ISODate = string;

export interface DateParts {
  readonly year: number;
  readonly month: number; // 1-12
  readonly day: number; // 1-31
}

const MS_PER_DAY = 86_400_000;
const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;

export function isLeapYear(year: number): boolean {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
}

export function daysInMonth(year: number, month: number): number {
  if (month < 1 || month > 12) {
    throw new ValidationError(`month out of range: ${month}`);
  }
  if (month === 2) return isLeapYear(year) ? 29 : 28;
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
}

export function parseDate(text: ISODate): DateParts {
  const match = ISO.exec(text);
  if (!match) {
    throw new ValidationError(`not an ISO date (YYYY-MM-DD): ${JSON.stringify(text)}`);
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) {
    throw new ValidationError(`invalid calendar date: ${text}`);
  }
  return { year, month, day };
}

export function formatDate({ year, month, day }: DateParts): ISODate {
  const pad = (n: number, width: number) => String(n).padStart(width, "0");
  return `${pad(year, 4)}-${pad(month, 2)}-${pad(day, 2)}`;
}

/** Days since 1970-01-01. Pure calendar arithmetic, no time zones involved. */
export function toEpochDay(date: ISODate): number {
  const { year, month, day } = parseDate(date);
  return Date.UTC(year, month - 1, day) / MS_PER_DAY;
}

export function fromEpochDay(epochDay: number): ISODate {
  return fromDate(new Date(epochDay * MS_PER_DAY));
}

/** The UTC calendar date of an instant. */
export function fromDate(instant: Date): ISODate {
  return formatDate({
    year: instant.getUTCFullYear(),
    month: instant.getUTCMonth() + 1,
    day: instant.getUTCDate(),
  });
}

export function addDays(date: ISODate, days: number): ISODate {
  return fromEpochDay(toEpochDay(date) + days);
}

/**
 * Add calendar months, clamping to the end of shorter months:
 * 2026-01-31 + 1 month = 2026-02-28; 2024-01-31 + 1 month = 2024-02-29.
 */
export function addMonths(date: ISODate, months: number): ISODate {
  if (!Number.isInteger(months)) {
    throw new ValidationError(`months must be an integer, got ${months}`);
  }
  const { year, month, day } = parseDate(date);
  const index = year * 12 + (month - 1) + months;
  const newYear = Math.floor(index / 12);
  const newMonth = (index % 12) + 1;
  return formatDate({ year: newYear, month: newMonth, day: Math.min(day, daysInMonth(newYear, newMonth)) });
}

/** Whole days from `start` to `end` (negative if `end` is earlier). */
export function daysBetween(start: ISODate, end: ISODate): number {
  return toEpochDay(end) - toEpochDay(start);
}

export function compareDates(a: ISODate, b: ISODate): -1 | 0 | 1 {
  const diff = toEpochDay(a) - toEpochDay(b);
  return diff === 0 ? 0 : diff < 0 ? -1 : 1;
}

export function maxDate(a: ISODate, b: ISODate): ISODate {
  return compareDates(a, b) >= 0 ? a : b;
}

export function minDate(a: ISODate, b: ISODate): ISODate {
  return compareDates(a, b) <= 0 ? a : b;
}
