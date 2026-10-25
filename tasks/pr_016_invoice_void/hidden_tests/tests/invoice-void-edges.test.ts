import { describe, expect, it } from "vitest";
import { InvoiceStateError, ValidationError } from "../src/errors";
import { Invoice } from "../src/invoice";
import { money } from "../src/money";

function issued(): Invoice {
  const invoice = new Invoice("EUR", { netDays: 10 });
  invoice.addLine({ description: "Audit", quantity: 2, unitPrice: money(15_000, "EUR"), taxRate: 0.19 });
  invoice.issue("INV-2026-0100", "2026-03-01");
  return invoice;
}

describe("voiding edge cases", () => {
  it("has no reason until voided", () => {
    expect(issued().voidReason).toBeUndefined();
  });

  it("keeps the number and issue date of a voided invoice", () => {
    const invoice = issued();
    invoice.void("sent to the wrong customer");
    expect(invoice.number).toBe("INV-2026-0100");
    expect(invoice.issuedOn).toBe("2026-03-01");
    expect(invoice.status).toBe("void");
  });

  it("rejects payments on a void invoice", () => {
    const invoice = issued();
    invoice.void("duplicate");
    expect(() => invoice.recordPayment(money(100, "EUR"), "2026-03-05")).toThrow(InvoiceStateError);
  });

  it("is not overdue long after its due date once void", () => {
    const invoice = issued();
    expect(invoice.isOverdue("2026-04-01")).toBe(true);
    invoice.void("written off by mistake, reissued");
    expect(invoice.isOverdue("2026-04-01")).toBe(false);
  });

  it("rejects an empty reason without changing the status", () => {
    const invoice = issued();
    expect(() => invoice.void("")).toThrow(ValidationError);
    expect(invoice.status).toBe("issued");
    expect(invoice.voidReason).toBeUndefined();
  });

  it("does not void when a payment exists, even if the reason is valid", () => {
    const invoice = issued();
    invoice.recordPayment(money(1, "EUR"), "2026-03-02");
    expect(() => invoice.void("customer cancelled")).toThrow(InvoiceStateError);
    expect(invoice.voidReason).toBeUndefined();
  });
});
