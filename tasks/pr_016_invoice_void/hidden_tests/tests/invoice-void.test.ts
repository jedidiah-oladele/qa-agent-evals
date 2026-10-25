import { describe, expect, it } from "vitest";
import { InvoiceStateError, ValidationError } from "../src/errors";
import { Invoice } from "../src/invoice";
import { money } from "../src/money";

function draft(): Invoice {
  const invoice = new Invoice("USD");
  invoice.addLine({ description: "Plan", quantity: 1, unitPrice: money(5_000, "USD"), taxRate: 0 });
  return invoice;
}

describe("Invoice.void", () => {
  it("voids a draft and keeps the reason", () => {
    const invoice = draft();
    invoice.void("  duplicate  ");
    expect(invoice.status).toBe("void");
    expect(invoice.voidReason).toBe("duplicate");
  });

  it("voids an issued invoice with no payments", () => {
    const invoice = draft();
    invoice.issue("INV-9", "2026-02-01");
    invoice.void("customer cancelled");
    expect(invoice.status).toBe("void");
    expect(invoice.isOverdue("2027-01-01")).toBe(false);
  });

  it("refuses to void once money was received", () => {
    const invoice = draft();
    invoice.issue("INV-9", "2026-02-01");
    invoice.recordPayment(money(1_000, "USD"), "2026-02-03");
    expect(() => invoice.void("oops")).toThrow(InvoiceStateError);
    expect(invoice.status).toBe("issued");
  });

  it("refuses to void paid or already void invoices", () => {
    const paid = draft();
    paid.issue("INV-1", "2026-02-01");
    paid.recordPayment(money(5_000, "USD"), "2026-02-02");
    expect(() => paid.void("late")).toThrow(InvoiceStateError);
    const voided = draft();
    voided.void("first");
    expect(() => voided.void("second")).toThrow(InvoiceStateError);
  });

  it("requires a reason", () => {
    expect(() => draft().void("   ")).toThrow(ValidationError);
  });

  it("blocks further changes after voiding", () => {
    const invoice = draft();
    invoice.void("test");
    expect(() => invoice.issue("INV-1", "2026-01-01")).toThrow(InvoiceStateError);
    expect(() => invoice.addLine({ description: "x", quantity: 1, unitPrice: money(1, "USD"), taxRate: 0 })).toThrow(
      InvoiceStateError,
    );
  });
});
