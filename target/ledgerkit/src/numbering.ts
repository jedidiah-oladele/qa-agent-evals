import { ValidationError } from "./errors";
import { type ISODate, parseDate } from "./dates";

/** Issues sequential invoice numbers such as "INV-2026-0042", restarting each year. */
export class InvoiceNumberer {
  private readonly counters = new Map<number, number>();

  constructor(
    readonly prefix = "INV",
    readonly width = 4,
  ) {
    if (!/^[A-Z][A-Z0-9]*$/.test(prefix)) {
      throw new ValidationError(`prefix must be upper-case alphanumeric, got ${JSON.stringify(prefix)}`);
    }
  }

  /** Continue numbering from an existing series (e.g. after a restart). */
  seed(year: number, lastIssued: number): void {
    this.counters.set(year, lastIssued);
  }

  next(issuedOn: ISODate): string {
    const { year } = parseDate(issuedOn);
    const n = (this.counters.get(year) ?? 0) + 1;
    this.counters.set(year, n);
    return `${this.prefix}-${year}-${String(n).padStart(this.width, "0")}`;
  }
}
