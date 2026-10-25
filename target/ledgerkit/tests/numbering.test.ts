import { describe, expect, it } from "vitest";
import { ValidationError } from "../src/errors";
import { InvoiceNumberer } from "../src/numbering";

describe("InvoiceNumberer", () => {
  it("numbers sequentially and restarts each year", () => {
    const numberer = new InvoiceNumberer();
    expect(numberer.next("2026-12-30")).toBe("INV-2026-0001");
    expect(numberer.next("2026-12-31")).toBe("INV-2026-0002");
    expect(numberer.next("2027-01-01")).toBe("INV-2027-0001");
    expect(numberer.next("2026-12-31")).toBe("INV-2026-0003");
  });

  it("supports custom prefix, width and seeding", () => {
    const numberer = new InvoiceNumberer("CR", 6);
    numberer.seed(2026, 41);
    expect(numberer.next("2026-05-05")).toBe("CR-2026-000042");
  });

  it("rejects bad prefixes and dates", () => {
    expect(() => new InvoiceNumberer("inv")).toThrow(ValidationError);
    expect(() => new InvoiceNumberer().next("2026-02-30")).toThrow(ValidationError);
  });
});
