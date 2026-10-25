import { CurrencyMismatchError, InvoiceStateError, ValidationError } from "./errors";
import { type ISODate, addDays, compareDates } from "./dates";
import { type Money, add, multiply, subtract, sum, zero } from "./money";

export type InvoiceStatus = "draft" | "issued" | "paid" | "void";

export interface InvoiceLine {
  readonly description: string;
  readonly quantity: number;
  readonly unitPrice: Money;
  /** Fraction, e.g. 0.2 for 20%. */
  readonly taxRate: number;
  /** Percentage off this line, 0-100. */
  readonly discountPercent?: number;
}

export interface Payment {
  readonly amount: Money;
  readonly receivedOn: ISODate;
}

export interface InvoiceOptions {
  /** Days between issue date and due date. */
  readonly netDays?: number;
}

export class Invoice {
  private readonly _lines: InvoiceLine[] = [];
  private readonly _payments: Payment[] = [];
  private _status: InvoiceStatus = "draft";
  private _number: string | undefined;
  private _issuedOn: ISODate | undefined;
  private _voidReason: string | undefined;
  readonly netDays: number;

  constructor(
    readonly currency: string,
    options: InvoiceOptions = {},
  ) {
    this.netDays = options.netDays ?? 30;
    if (!Number.isInteger(this.netDays) || this.netDays < 0) {
      throw new ValidationError(`netDays must be a non-negative integer, got ${this.netDays}`);
    }
    zero(currency);
  }

  get status(): InvoiceStatus {
    return this._status;
  }
  get number(): string | undefined {
    return this._number;
  }
  get issuedOn(): ISODate | undefined {
    return this._issuedOn;
  }
  get dueOn(): ISODate | undefined {
    return this._issuedOn === undefined ? undefined : addDays(this._issuedOn, this.netDays);
  }
  get voidReason(): string | undefined {
    return this._voidReason;
  }
  get lines(): readonly InvoiceLine[] {
    return this._lines;
  }
  get payments(): readonly Payment[] {
    return this._payments;
  }

  private requireStatus(...allowed: InvoiceStatus[]): void {
    if (!allowed.includes(this._status)) {
      throw new InvoiceStateError(`invoice is ${this._status}; expected ${allowed.join(" or ")}`);
    }
  }

  addLine(line: InvoiceLine): void {
    this.requireStatus("draft");
    if (line.unitPrice.currency !== this.currency) {
      throw new CurrencyMismatchError(this.currency, line.unitPrice.currency);
    }
    if (!Number.isInteger(line.quantity) || line.quantity <= 0) {
      throw new ValidationError(`quantity must be a positive integer, got ${line.quantity}`);
    }
    if (!(line.taxRate >= 0 && line.taxRate < 1)) {
      throw new ValidationError(`taxRate must be in [0, 1), got ${line.taxRate}`);
    }
    const discount = line.discountPercent ?? 0;
    if (!(discount >= 0 && discount <= 100)) {
      throw new ValidationError(`discountPercent must be in [0, 100], got ${discount}`);
    }
    if (line.unitPrice.minor < 0) {
      throw new ValidationError("unit price cannot be negative");
    }
    this._lines.push(line);
  }

  removeLine(index: number): void {
    this.requireStatus("draft");
    if (index < 0 || index >= this._lines.length) {
      throw new ValidationError(`no line at index ${index}`);
    }
    this._lines.splice(index, 1);
  }

  /** Line amount after its discount, before tax. */
  lineNet(line: InvoiceLine): Money {
    const gross = multiply(line.unitPrice, line.quantity);
    const discount = multiply(gross, (line.discountPercent ?? 0) / 100);
    return subtract(gross, discount);
  }

  /** Tax for one line, rounded half-up on that line. */
  lineTax(line: InvoiceLine): Money {
    return multiply(this.lineNet(line), line.taxRate);
  }

  get subtotal(): Money {
    return sum(
      this._lines.map((l) => this.lineNet(l)),
      this.currency,
    );
  }

  get taxTotal(): Money {
    return sum(
      this._lines.map((l) => this.lineTax(l)),
      this.currency,
    );
  }

  get total(): Money {
    return add(this.subtotal, this.taxTotal);
  }

  get amountPaid(): Money {
    return sum(
      this._payments.map((p) => p.amount),
      this.currency,
    );
  }

  get balance(): Money {
    return subtract(this.total, this.amountPaid);
  }

  issue(number: string, issuedOn: ISODate): void {
    this.requireStatus("draft");
    if (this._lines.length === 0) {
      throw new InvoiceStateError("cannot issue an invoice without lines");
    }
    if (!number.trim()) {
      throw new ValidationError("invoice number is required");
    }
    addDays(issuedOn, 0); // validates the date
    this._number = number;
    this._issuedOn = issuedOn;
    this._status = "issued";
  }

  recordPayment(amount: Money, receivedOn: ISODate): void {
    this.requireStatus("issued");
    if (amount.currency !== this.currency) {
      throw new CurrencyMismatchError(this.currency, amount.currency);
    }
    if (amount.minor <= 0) {
      throw new ValidationError("payment must be positive");
    }
    if (amount.minor > this.balance.minor) {
      throw new ValidationError("payment exceeds the outstanding balance");
    }
    this._payments.push({ amount, receivedOn });
    if (this.balance.minor === 0) {
      this._status = "paid";
    }
  }

  isOverdue(today: ISODate): boolean {
    const due = this.dueOn;
    return this._status === "issued" && due !== undefined && compareDates(today, due) > 0;
  }

  /**
   * Cancel the invoice. Drafts can always be voided; issued invoices only
   * while nothing has been paid against them. A reason is required for the
   * audit trail.
   */
  void(reason: string): void {
    this.requireStatus("draft", "issued");
    if (!reason.trim()) {
      throw new ValidationError("a reason is required to void an invoice");
    }
    if (this._payments.length > 0) {
      throw new InvoiceStateError("cannot void an invoice with payments; issue a credit note instead");
    }
    this._voidReason = reason.trim();
    this._status = "void";
  }
}
