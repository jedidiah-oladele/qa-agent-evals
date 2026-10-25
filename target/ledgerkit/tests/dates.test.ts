import { describe, expect, it } from "vitest";
import {
  addDays,
  addMonths,
  compareDates,
  daysBetween,
  daysInMonth,
  formatDate,
  fromDate,
  isLeapYear,
  maxDate,
  minDate,
  parseDate,
  toEpochDay,
} from "../src/dates";
import { ValidationError } from "../src/errors";

describe("calendar basics", () => {
  it("knows leap years", () => {
    expect([2024, 2000, 2023, 1900].map(isLeapYear)).toEqual([true, true, false, false]);
  });

  it("knows month lengths", () => {
    expect(daysInMonth(2026, 2)).toBe(28);
    expect(daysInMonth(2028, 2)).toBe(29);
    expect(daysInMonth(2026, 4)).toBe(30);
    expect(daysInMonth(2026, 12)).toBe(31);
    expect(() => daysInMonth(2026, 13)).toThrow(ValidationError);
  });
});

describe("parse and format", () => {
  it("round-trips", () => {
    expect(parseDate("2026-03-09")).toEqual({ year: 2026, month: 3, day: 9 });
    expect(formatDate({ year: 7, month: 1, day: 2 })).toBe("0007-01-02");
  });

  it.each(["2026-02-29", "2026-13-01", "2026-00-10", "2026-1-01", "20260101", "2026-04-31"])(
    "rejects %s",
    (text) => {
      expect(() => parseDate(text)).toThrow(ValidationError);
    },
  );
});

describe("arithmetic", () => {
  it("adds days across month and year ends", () => {
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(addDays("2024-02-28", 1)).toBe("2024-02-29");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
  });

  it("adds months with end-of-month clamping", () => {
    expect(addMonths("2026-01-31", 1)).toBe("2026-02-28");
    expect(addMonths("2024-01-31", 1)).toBe("2024-02-29");
    expect(addMonths("2026-03-31", 1)).toBe("2026-04-30");
    expect(addMonths("2026-01-15", 12)).toBe("2027-01-15");
    expect(addMonths("2026-11-30", 3)).toBe("2027-02-28");
  });

  it("subtracts months", () => {
    expect(addMonths("2026-03-31", -1)).toBe("2026-02-28");
    expect(addMonths("2026-01-10", -1)).toBe("2025-12-10");
  });

  it("requires integer months", () => {
    expect(() => addMonths("2026-01-01", 1.5)).toThrow(ValidationError);
  });

  it("counts days between dates", () => {
    expect(daysBetween("2026-01-01", "2026-02-01")).toBe(31);
    expect(daysBetween("2024-02-01", "2024-03-01")).toBe(29);
    expect(daysBetween("2026-03-01", "2026-02-01")).toBe(-28);
    expect(daysBetween("2026-03-28", "2026-03-30")).toBe(2);
  });

  it("compares and picks min/max", () => {
    expect(compareDates("2026-01-02", "2026-01-01")).toBe(1);
    expect(compareDates("2026-01-01", "2026-01-01")).toBe(0);
    expect(minDate("2026-05-01", "2026-04-30")).toBe("2026-04-30");
    expect(maxDate("2026-05-01", "2026-04-30")).toBe("2026-05-01");
  });

  it("converts epoch days and instants", () => {
    expect(toEpochDay("1970-01-02")).toBe(1);
    expect(fromDate(new Date("2026-06-30T23:59:59Z"))).toBe("2026-06-30");
    expect(fromDate(new Date("2026-06-30T23:30:00-02:00"))).toBe("2026-07-01");
  });
});
