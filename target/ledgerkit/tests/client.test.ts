import { describe, expect, it } from "vitest";
import { LedgerClient } from "../src/client";
import { ApiError, NetworkError, TimeoutError, ValidationError } from "../src/errors";
import { fakeFetch, json, recordingSleep } from "./helpers/fake-fetch";

function client(fetchImpl: typeof fetch, extra: Partial<ConstructorParameters<typeof LedgerClient>[0]> = {}) {
  const { sleep, delays } = recordingSleep();
  const c = new LedgerClient({ baseUrl: "https://api.ledger.test/v1/", apiKey: "sk_test", fetch: fetchImpl, sleep, ...extra });
  return { client: c, delays };
}

describe("buildUrl", () => {
  const { client: c } = client(fakeFetch().fetch);

  it("joins base and path with exactly one slash", () => {
    expect(c.buildUrl("/invoices")).toBe("https://api.ledger.test/v1/invoices");
    expect(c.buildUrl("invoices")).toBe("https://api.ledger.test/v1/invoices");
  });

  it("encodes query values and repeats array keys", () => {
    expect(c.buildUrl("/search", { q: "a&b c", tag: ["x/y", 2], empty: undefined, none: null, flag: false })).toBe(
      "https://api.ledger.test/v1/search?q=a%26b%20c&tag=x%2Fy&tag=2&flag=false",
    );
  });
});

describe("constructor", () => {
  it("validates options", () => {
    expect(() => new LedgerClient({ baseUrl: "ftp://x", apiKey: "k" })).toThrow(ValidationError);
    expect(() => new LedgerClient({ baseUrl: "https://x", apiKey: "" })).toThrow(ValidationError);
  });
});

describe("request", () => {
  it("sends auth and JSON headers and parses the body", async () => {
    const fake = fakeFetch(json(200, { id: "inv_1" }));
    const { client: c } = client(fake.fetch);
    await expect(c.request("POST", "/invoices", { body: { a: 1 } })).resolves.toEqual({ id: "inv_1" });
    const init = fake.calls[0]!.init;
    expect(init.method).toBe("POST");
    expect(init.body).toBe('{"a":1}');
    expect(init.headers).toMatchObject({
      Authorization: "Bearer sk_test",
      Accept: "application/json",
      "Content-Type": "application/json",
    });
  });

  it("returns undefined for 204", async () => {
    const fake = fakeFetch(() => new Response(null, { status: 204 }));
    await expect(client(fake.fetch).client.request("DELETE", "/invoices/1")).resolves.toBeUndefined();
  });

  it("maps error bodies to ApiError", async () => {
    const fake = fakeFetch(json(422, { error: { code: "invalid_currency", message: "XYZ is not supported" } }));
    const error = await client(fake.fetch).client.request("GET", "/x").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, code: "invalid_currency", message: "XYZ is not supported" });
  });

  it("falls back to the status line for non-JSON errors", async () => {
    const fake = fakeFetch(() => new Response("<html>", { status: 500, statusText: "Internal Server Error" }));
    const error = await client(fake.fetch).client.request("GET", "/x").catch((e) => e);
    expect(error).toMatchObject({ status: 500, code: "http_error", message: "500 Internal Server Error" });
  });

  it("retries retryable statuses with exponential backoff", async () => {
    const fake = fakeFetch(json(503, {}), json(502, {}), json(200, { ok: true }));
    const { client: c, delays } = client(fake.fetch);
    await expect(c.request("GET", "/x")).resolves.toEqual({ ok: true });
    expect(delays).toEqual([250, 500]);
    expect(fake.calls).toHaveLength(3);
  });

  it("gives up after maxRetries", async () => {
    const fake = fakeFetch(json(503, {}), json(503, {}), json(503, { error: { code: "down", message: "down" } }));
    const error = await client(fake.fetch).client.request("GET", "/x").catch((e) => e);
    expect(error).toMatchObject({ status: 503, code: "down" });
    expect(fake.calls).toHaveLength(3);
  });

  it("does not retry client errors", async () => {
    const fake = fakeFetch(json(404, {}));
    await expect(client(fake.fetch).client.request("GET", "/x")).rejects.toBeInstanceOf(ApiError);
    expect(fake.calls).toHaveLength(1);
  });

  it("retries network errors and surfaces the last one", async () => {
    const boom = () => {
      throw new TypeError("socket hang up");
    };
    const fake = fakeFetch(boom, boom);
    const { client: c } = client(fake.fetch, { maxRetries: 1 });
    await expect(c.request("GET", "/x")).rejects.toBeInstanceOf(NetworkError);
    expect(fake.calls).toHaveLength(2);
  });

  it("times out slow requests", async () => {
    const hang = ({ init }: { init: RequestInit }) =>
      new Promise<Response>((_, reject) => {
        init.signal!.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      });
    const fake = fakeFetch(hang);
    const { client: c } = client(fake.fetch, { timeoutMs: 5, maxRetries: 0 });
    await expect(c.request("GET", "/slow")).rejects.toBeInstanceOf(TimeoutError);
  });

  it("caps backoff at maxRetryDelayMs", async () => {
    const fake = fakeFetch(json(503, {}), json(503, {}), json(503, {}), json(200, {}));
    const { client: c, delays } = client(fake.fetch, { maxRetries: 3, retryBaseMs: 400, maxRetryDelayMs: 1000 });
    await c.request("GET", "/x");
    expect(delays).toEqual([400, 800, 1000]);
  });
});

describe("resource helpers", () => {
  it("encodes ids in paths", async () => {
    const fake = fakeFetch(json(200, { id: "a/b" }));
    await client(fake.fetch).client.getInvoice("a/b");
    expect(fake.calls[0]!.url).toBe("https://api.ledger.test/v1/invoices/a%2Fb");
  });

  it("lists with query parameters", async () => {
    const fake = fakeFetch(json(200, { data: [], next_cursor: null }));
    await client(fake.fetch).client.listInvoices({ status: "issued", limit: 50 });
    expect(fake.calls[0]!.url).toBe("https://api.ledger.test/v1/invoices?status=issued&limit=50");
  });
});
