import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { addDays, daysBetween, fromEpochDay, toEpochDay } from "../src/dates";
import { Invoice } from "../src/invoice";
import { money } from "../src/money";

// Calendar dates must not depend on the machine's time zone. Node re-reads
// process.env.TZ when it is assigned, so each block runs in a different zone.
const ZONES = ["America/New_York", "America/Los_Angeles", "Pacific/Pago_Pago", "Asia/Tokyo", "Pacific/Kiritimati", "UTC"];

function invoiceIssuedOn(issuedOn: string, netDays: number): Invoice {
  const invoice = new Invoice("USD", { netDays });
  invoice.addLine({ description: "Support plan", quantity: 1, unitPrice: money(12_500, "USD"), taxRate: 0 });
  invoice.issue("INV-2026-0311", issuedOn);
  return invoice;
}

describe.each(ZONES)("calendar arithmetic with TZ=%s", (zone) => {
  let saved: string | undefined;
  beforeAll(() => {
    saved = process.env.TZ;
    process.env.TZ = zone;
  });
  afterAll(() => {
    if (saved === undefined) delete process.env.TZ;
    else process.env.TZ = saved;
  });

  it("adds days across month and year ends", () => {
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(addDays("2024-02-28", 1)).toBe("2024-02-29");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
    expect(addDays("2026-07-15", 0)).toBe("2026-07-15");
  });

  it("adds days across daylight-saving changes", () => {
    expect(addDays("2026-03-01", 14)).toBe("2026-03-15");
    expect(addDays("2026-10-25", 14)).toBe("2026-11-08");
    expect(addDays("2026-03-29", -30)).toBe("2026-02-27");
    expect(addDays("2026-01-01", 365)).toBe("2027-01-01");
  });

  it("computes invoice due dates", () => {
    expect(invoiceIssuedOn("2026-10-20", 14).dueOn).toBe("2026-11-03");
    expect(invoiceIssuedOn("2026-12-20", 30).dueOn).toBe("2027-01-19");
    expect(invoiceIssuedOn("2026-03-05", 0).dueOn).toBe("2026-03-05");
  });

  it("becomes overdue the day after the due date", () => {
    const invoice = invoiceIssuedOn("2026-02-27", 10);
    expect(invoice.isOverdue("2026-03-09")).toBe(false);
    expect(invoice.isOverdue("2026-03-10")).toBe(true);
  });

  it("keeps epoch-day conversions exact", () => {
    expect(fromEpochDay(toEpochDay("2026-11-01"))).toBe("2026-11-01");
    expect(daysBetween("2026-03-01", "2026-04-01")).toBe(31);
  });
});
