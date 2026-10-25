/** Base class for every error ledgerkit throws on purpose. */
export class LedgerError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
  }
}

export class UnknownCurrencyError extends LedgerError {}

export class CurrencyMismatchError extends LedgerError {
  constructor(
    readonly left: string,
    readonly right: string,
  ) {
    super(`currency mismatch: ${left} vs ${right}`);
  }
}

export class ValidationError extends LedgerError {}

export class InvoiceStateError extends LedgerError {}

export class RateNotFoundError extends LedgerError {}

/** The API answered with a non-2xx status. */
export class ApiError extends LedgerError {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

/** The request did not complete within the configured timeout. */
export class TimeoutError extends LedgerError {}

/** The request failed before any HTTP response arrived. */
export class NetworkError extends LedgerError {}
