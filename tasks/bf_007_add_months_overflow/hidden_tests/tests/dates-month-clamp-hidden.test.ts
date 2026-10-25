import { describe, expect, it } from "vitest";
import { billingPeriods, nthPeriod, periodDays, prorate } from "../src/billing";
import { addMonths, daysInMonth, formatDate, parseDate } from "../src/dates";
import { money } from "../src/money";

describe("addMonths across leap and common years", () => {
  it("clamps to Feb 29 when the target year is a leap year", () => {
    expect(addMonths("2027-11-30", 3)).toBe("2028-02-29");
    expect(addMonths("2023-12-31", 2)).toBe("2024-02-29");
    expect(addMonths("2029-01-31", -11)).toBe("2028-02-29");
  });

  it("never produces Feb 29 in a common year", () => {
    expect(addMonths("2024-02-29", 12)).toBe("2025-02-28");
    expect(addMonths("2024-01-31", 13)).toBe("2025-02-28");
    expect(addMonths("2024-03-31", -13)).toBe("2023-02-28");
    expect(addMonths("2024-02-29", -12)).toBe("2023-02-28");
  });

  it("returns a valid calendar date clamped to the target month for any offset", () => {
    for (const year of [2023, 2024, 2025]) {
      for (let month = 1; month <= 12; month++) {
        for (const day of [1, 28, 29, 30, 31]) {
          if (day > daysInMonth(year, month)) continue;
          const start = formatDate({ year, month, day });
          for (let k = -26; k <= 26; k++) {
            const result = addMonths(start, k);
            const parts = parseDate(result);
            const index = year * 12 + (month - 1) + k;
            expect(parts.year).toBe(Math.floor(index / 12));
            expect(parts.month).toBe((index % 12) + 1);
            expect(parts.day).toBe(Math.min(day, daysInMonth(parts.year, parts.month)));
          }
        }
      }
    }
  });

  it("still handles negative offsets across year boundaries", () => {
    expect(addMonths("2026-01-10", -1)).toBe("2025-12-10");
    expect(addMonths("2026-01-31", -13)).toBe("2024-12-31");
    expect(addMonths("2026-03-15", -27)).toBe("2023-12-15");
    expect(addMonths("2026-05-31", 0)).toBe("2026-05-31");
  });
});

describe("billing periods anchored near February", () => {
  it("renews a yearly plan anchored on a leap day on Feb 28 in common years", () => {
    expect(nthPeriod("2024-02-29", 1, "yearly")).toEqual({ start: "2025-02-28", end: "2026-02-28" });
    expect(billingPeriods("2024-02-29", "2029-01-01", "yearly").map((p) => p.start)).toEqual([
      "2024-02-29",
      "2025-02-28",
      "2026-02-28",
      "2027-02-28",
      "2028-02-29",
    ]);
  });

  it("uses Feb 29 for a quarterly plan anchored on Nov 30 in a leap year", () => {
    const period = nthPeriod("2027-11-30", 1, "quarterly");
    expect(period).toEqual({ start: "2028-02-29", end: "2028-05-30" });
    expect(periodDays(period)).toBe(91);
  });

  it("prorates the leap-year February of a month-end plan over 31 days", () => {
    const march = nthPeriod("2027-12-31", 2, "monthly");
    expect(march).toEqual({ start: "2028-02-29", end: "2028-03-31" });
    expect(prorate(money(3_100, "USD"), march, "2028-03-21", "2028-04-15").minor).toBe(1_000);
  });
});
