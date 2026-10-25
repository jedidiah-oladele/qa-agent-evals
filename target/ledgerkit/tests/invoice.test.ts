import { beforeEach, describe, expect, it } from "vitest";
import { CurrencyMismatchError, InvoiceStateError, ValidationError } from "../src/errors";
import { Invoice } from "../src/invoice";
import { money } from "../src/money";

function sampleInvoice(): Invoice {
  const invoice = new Invoice("USD", { netDays: 14 });
  invoice.addLine({ description: "Consulting", quantity: 3, unitPrice: money(12_000, "USD"), taxRate: 0.075 });
  invoice.addLine({ description: "Hosting", quantity: 1, unitPrice: money(1_999, "USD"), taxRate: 0.2 });
  return invoice;
}

describe("Invoice totals", () => {
  it("adds line nets and per-line rounded tax", () => {
    const invoice = sampleInvoice();
    expect(invoice.subtotal.minor).toBe(37_999);
    // 36000 * 0.075 = 2700 ; 1999 * 0.2 = 399.8 -> 400
    expect(invoice.taxTotal.minor).toBe(3_100);
    expect(invoice.total.minor).toBe(41_099);
  });

  it("applies line discounts before tax", () => {
    const invoice = new Invoice("USD");
    invoice.addLine({ description: "Seats", quantity: 4, unitPrice: money(2_500, "USD"), taxRate: 0.1, discountPercent: 15 });
    const line = invoice.lines[0]!;
    expect(invoice.lineNet(line).minor).toBe(8_500);
    expect(invoice.lineTax(line).minor).toBe(850);
  });

  it("an empty invoice totals zero", () => {
    expect(new Invoice("EUR").total).toEqual(money(0, "EUR"));
  });
});

describe("Invoice validation", () => {
  let invoice: Invoice;
  beforeEach(() => {
    invoice = new Invoice("USD");
  });

  it("rejects lines in another currency", () => {
    expect(() => invoice.addLine({ description: "x", quantity: 1, unitPrice: money(1, "EUR"), taxRate: 0 })).toThrow(
      CurrencyMismatchError,
    );
  });

  it.each([0, -1, 1.5])("rejects quantity %d", (quantity) => {
    expect(() => invoice.addLine({ description: "x", quantity, unitPrice: money(1, "USD"), taxRate: 0 })).toThrow(
      ValidationError,
    );
  });

  it("rejects bad tax rates, discounts and prices", () => {
    const base = { description: "x", quantity: 1, unitPrice: money(1, "USD"), taxRate: 0 };
    expect(() => invoice.addLine({ ...base, taxRate: 1 })).toThrow(ValidationError);
    expect(() => invoice.addLine({ ...base, taxRate: -0.1 })).toThrow(ValidationError);
    expect(() => invoice.addLine({ ...base, discountPercent: 101 })).toThrow(ValidationError);
    expect(() => invoice.addLine({ ...base, unitPrice: money(-1, "USD") })).toThrow(ValidationError);
  });

  it("validates netDays", () => {
    expect(() => new Invoice("USD", { netDays: -1 })).toThrow(ValidationError);
  });

  it("removes lines by index while in draft", () => {
    const inv = sampleInvoice();
    inv.removeLine(0);
    expect(inv.lines.map((l) => l.description)).toEqual(["Hosting"]);
    expect(() => inv.removeLine(5)).toThrow(ValidationError);
  });
});

describe("Invoice lifecycle", () => {
  it("issues with a number and due date", () => {
    const invoice = sampleInvoice();
    invoice.issue("INV-2026-0001", "2026-10-20");
    expect(invoice.status).toBe("issued");
    expect(invoice.number).toBe("INV-2026-0001");
    expect(invoice.dueOn).toBe("2026-11-03");
  });

  it("cannot issue an empty invoice or issue twice", () => {
    expect(() => new Invoice("USD").issue("INV-1", "2026-01-01")).toThrow(InvoiceStateError);
    const invoice = sampleInvoice();
    invoice.issue("INV-1", "2026-01-01");
    expect(() => invoice.issue("INV-2", "2026-01-02")).toThrow(InvoiceStateError);
  });

  it("is immutable once issued", () => {
    const invoice = sampleInvoice();
    invoice.issue("INV-1", "2026-01-01");
    expect(() => invoice.addLine({ description: "late", quantity: 1, unitPrice: money(1, "USD"), taxRate: 0 })).toThrow(
      InvoiceStateError,
    );
    expect(() => invoice.removeLine(0)).toThrow(InvoiceStateError);
  });

  it("tracks partial payments and becomes paid at zero balance", () => {
    const invoice = sampleInvoice();
    invoice.issue("INV-1", "2026-01-01");
    invoice.recordPayment(money(41_000, "USD"), "2026-01-05");
    expect(invoice.balance.minor).toBe(99);
    expect(invoice.status).toBe("issued");
    invoice.recordPayment(money(99, "USD"), "2026-01-06");
    expect(invoice.status).toBe("paid");
    expect(invoice.amountPaid.minor).toBe(41_099);
  });

  it("rejects overpayment, payments on drafts and wrong currencies", () => {
    const invoice = sampleInvoice();
    expect(() => invoice.recordPayment(money(1, "USD"), "2026-01-01")).toThrow(InvoiceStateError);
    invoice.issue("INV-1", "2026-01-01");
    expect(() => invoice.recordPayment(money(41_100, "USD"), "2026-01-02")).toThrow(ValidationError);
    expect(() => invoice.recordPayment(money(0, "USD"), "2026-01-02")).toThrow(ValidationError);
    expect(() => invoice.recordPayment(money(10, "EUR"), "2026-01-02")).toThrow(CurrencyMismatchError);
  });

  it("is overdue only after the due date while unpaid", () => {
    const invoice = sampleInvoice();
    expect(invoice.isOverdue("2030-01-01")).toBe(false);
    invoice.issue("INV-1", "2026-01-01");
    expect(invoice.isOverdue("2026-01-15")).toBe(false);
    expect(invoice.isOverdue("2026-01-16")).toBe(true);
    invoice.recordPayment(invoice.balance, "2026-01-20");
    expect(invoice.isOverdue("2026-02-01")).toBe(false);
  });
});
