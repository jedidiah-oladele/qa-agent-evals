import { ApiError, NetworkError, TimeoutError, ValidationError } from "./errors";

export type QueryValue = string | number | boolean | undefined | null | ReadonlyArray<string | number>;
export type Query = Readonly<Record<string, QueryValue>>;

export interface ClientOptions {
  readonly baseUrl: string;
  readonly apiKey: string;
  readonly fetch?: typeof fetch;
  /** Per-attempt timeout. */
  readonly timeoutMs?: number;
  /** Retries after the first attempt for 429/502/503/504 and network errors. */
  readonly maxRetries?: number;
  /** First backoff delay; doubles on every retry. */
  readonly retryBaseMs?: number;
  /** Upper bound for any single wait, including server-requested ones. */
  readonly maxRetryDelayMs?: number;
  readonly sleep?: (ms: number) => Promise<void>;
  readonly now?: () => number;
}

export interface RequestOptions {
  readonly query?: Query;
  readonly body?: unknown;
}

export interface Page<T> {
  readonly data: T[];
  readonly next_cursor: string | null;
}

export interface InvoiceDTO {
  readonly id: string;
  readonly number: string;
  readonly currency: string;
  readonly total_minor: number;
  readonly status: string;
}

const RETRYABLE_STATUS = new Set([429, 502, 503, 504]);

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * Parse a Retry-After header: either delay-seconds ("120") or an HTTP-date.
 * Returns milliseconds to wait, or undefined when the header is absent or
 * unparseable. Dates in the past mean "retry now".
 */
export function parseRetryAfter(value: string | null, nowMs: number): number | undefined {
  if (value === null) return undefined;
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) {
    return Number(trimmed) * 1000;
  }
  // HTTP-dates always contain a weekday/month name; this also stops
  // Date.parse from reading "-5" as the year 5 BC.
  if (!/[A-Za-z]/.test(trimmed)) return undefined;
  const at = Date.parse(trimmed);
  if (Number.isNaN(at)) return undefined;
  return Math.max(0, at - nowMs);
}

export class LedgerClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;
  private readonly retryBaseMs: number;
  private readonly maxRetryDelayMs: number;
  private readonly sleep: (ms: number) => Promise<void>;
  private readonly now: () => number;

  constructor(options: ClientOptions) {
    if (!/^https?:\/\//.test(options.baseUrl)) {
      throw new ValidationError(`baseUrl must start with http:// or https://, got ${options.baseUrl}`);
    }
    if (!options.apiKey) {
      throw new ValidationError("apiKey is required");
    }
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.apiKey = options.apiKey;
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.timeoutMs = options.timeoutMs ?? 10_000;
    this.maxRetries = options.maxRetries ?? 2;
    this.retryBaseMs = options.retryBaseMs ?? 250;
    this.maxRetryDelayMs = options.maxRetryDelayMs ?? 30_000;
    this.sleep = options.sleep ?? defaultSleep;
    this.now = options.now ?? Date.now;
  }

  /** Join the base URL, a path and an encoded query string. */
  buildUrl(path: string, query: Query = {}): string {
    const cleanPath = path.startsWith("/") ? path : `/${path}`;
    const parts: string[] = [];
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null) continue;
      const values = Array.isArray(value) ? value : [value];
      for (const v of values) {
        parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(v))}`);
      }
    }
    return `${this.baseUrl}${cleanPath}${parts.length ? `?${parts.join("&")}` : ""}`;
  }

  private backoff(retry: number): number {
    return Math.min(this.retryBaseMs * 2 ** retry, this.maxRetryDelayMs);
  }

  async request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    const url = this.buildUrl(path, options.query);
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.apiKey}`,
      Accept: "application/json",
    };
    let body: string | undefined;
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(options.body);
    }

    for (let attempt = 0; ; attempt++) {
      const canRetry = attempt < this.maxRetries;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);
      let response: Response;
      try {
        response = await this.fetchImpl(url, { method, headers, body, signal: controller.signal });
      } catch (error) {
        const failure = controller.signal.aborted
          ? new TimeoutError(`${method} ${path} timed out after ${this.timeoutMs}ms`)
          : new NetworkError(`${method} ${path} failed: ${(error as Error).message}`);
        if (!canRetry) throw failure;
        await this.sleep(this.backoff(attempt));
        continue;
      } finally {
        clearTimeout(timer);
      }

      if (response.ok) {
        if (response.status === 204) return undefined as T;
        return (await response.json()) as T;
      }

      if (RETRYABLE_STATUS.has(response.status) && canRetry) {
        const requested = parseRetryAfter(response.headers.get("Retry-After"), this.now());
        const delay = requested === undefined ? this.backoff(attempt) : Math.min(requested, this.maxRetryDelayMs);
        await this.sleep(delay);
        continue;
      }
      throw await this.toApiError(response);
    }
  }

  private async toApiError(response: Response): Promise<ApiError> {
    let code = "http_error";
    let message = `${response.status} ${response.statusText}`.trim();
    try {
      const payload = (await response.json()) as { error?: { code?: string; message?: string } };
      code = payload.error?.code ?? code;
      message = payload.error?.message ?? message;
    } catch {
      // Body was not JSON; keep the status line.
    }
    return new ApiError(response.status, code, message);
  }

  getInvoice(id: string): Promise<InvoiceDTO> {
    return this.request("GET", `/invoices/${encodeURIComponent(id)}`);
  }

  listInvoices(query: Query = {}): Promise<Page<InvoiceDTO>> {
    return this.request("GET", "/invoices", { query });
  }

  createInvoice(payload: Omit<InvoiceDTO, "id" | "status">): Promise<InvoiceDTO> {
    return this.request("POST", "/invoices", { body: payload });
  }

  /**
   * Iterate over every item of a cursor-paginated collection, fetching pages
   * lazily. Stops when the server returns no `next_cursor`. A cursor that
   * repeats would loop forever, so it raises instead.
   */
  async *paginate<T>(path: string, query: Query = {}): AsyncGenerator<T, void, undefined> {
    const seen = new Set<string>();
    let cursor: string | null = null;
    do {
      const page: Page<T> = await this.request<Page<T>>("GET", path, {
        query: cursor === null ? query : { ...query, cursor },
      });
      yield* page.data;
      cursor = page.next_cursor;
      if (cursor !== null) {
        if (seen.has(cursor)) {
          throw new ApiError(200, "cursor_loop", `server repeated cursor ${cursor}`);
        }
        seen.add(cursor);
      }
    } while (cursor !== null);
  }
}
