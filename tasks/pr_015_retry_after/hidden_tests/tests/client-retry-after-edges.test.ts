import { afterEach, describe, expect, it, vi } from "vitest";
import { LedgerClient, parseRetryAfter } from "../src/client";
import { ApiError } from "../src/errors";
import { fakeFetch, json, recordingSleep } from "./helpers/fake-fetch";

const NOW = Date.parse("2026-11-03T08:15:00Z");

function setup(responses: Parameters<typeof fakeFetch>, options: { maxRetries?: number; maxRetryDelayMs?: number } = {}) {
  const fake = fakeFetch(...responses);
  const { sleep, delays } = recordingSleep();
  const client = new LedgerClient({
    baseUrl: "https://api.ledger.test",
    apiKey: "k",
    fetch: fake.fetch,
    sleep,
    now: () => NOW,
    ...options,
  });
  return { client, delays, fake };
}

describe("parseRetryAfter edge cases", () => {
  it("accepts large delay-seconds with surrounding whitespace", () => {
    expect(parseRetryAfter("  120\t", NOW)).toBe(120_000);
  });

  it("rejects fractional, signed and empty values", () => {
    expect(parseRetryAfter("1.5", NOW)).toBeUndefined();
    expect(parseRetryAfter("+3", NOW)).toBeUndefined();
    expect(parseRetryAfter("", NOW)).toBeUndefined();
    expect(parseRetryAfter("   ", NOW)).toBeUndefined();
  });

  it("accepts the obsolete RFC 850 date form", () => {
    expect(parseRetryAfter("Tuesday, 03-Nov-26 08:15:05 GMT", NOW)).toBe(5_000);
  });
});

describe("Retry-After in the retry loop", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("retries immediately when the server sends Retry-After: 0", async () => {
    const { client, delays } = setup([json(429, {}, { "Retry-After": "0" }), json(200, { ok: true })]);
    await expect(client.request("GET", "/x")).resolves.toEqual({ ok: true });
    expect(delays).toEqual([0]);
  });

  it("retries immediately when the requested date is already past", async () => {
    const { client, delays } = setup([json(503, {}, { "Retry-After": "Tue, 03 Nov 2026 08:00:00 GMT" }), json(200, {})]);
    await client.request("GET", "/x");
    expect(delays).toEqual([0]);
  });

  it("honours the header on 502 and 504 as well", async () => {
    const { client, delays } = setup([
      json(502, {}, { "Retry-After": "1" }),
      json(504, {}, { "Retry-After": "2" }),
      json(200, {}),
    ]);
    await client.request("GET", "/x");
    expect(delays).toEqual([1_000, 2_000]);
  });

  it("keeps the backoff schedule for a later attempt without the header", async () => {
    const { client, delays } = setup([json(429, {}, { "Retry-After": "1" }), json(503, {}), json(200, {})]);
    await client.request("GET", "/x");
    expect(delays).toEqual([1_000, 500]);
  });

  it("caps server-requested waits at the default maxRetryDelayMs", async () => {
    const { client, delays } = setup([json(429, {}, { "Retry-After": "600" }), json(200, {})]);
    await client.request("GET", "/x");
    expect(delays).toEqual([30_000]);
  });

  it("does not wait when no retries are left", async () => {
    const { client, delays } = setup([json(429, {}, { "Retry-After": "5" })], { maxRetries: 0 });
    const error = await client.request("GET", "/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(429);
    expect(delays).toEqual([]);
  });

  it("ignores the header on statuses that are not retried", async () => {
    const { client, delays } = setup([json(400, { error: { code: "bad", message: "no" } }, { "Retry-After": "1" })]);
    await expect(client.request("GET", "/x")).rejects.toBeInstanceOf(ApiError);
    expect(delays).toEqual([]);
  });

  it("uses the system clock when no `now` option is given", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    const fake = fakeFetch(json(503, {}, { "Retry-After": "Tue, 03 Nov 2026 08:15:03 GMT" }), json(200, {}));
    const { sleep, delays } = recordingSleep();
    const client = new LedgerClient({ baseUrl: "https://api.ledger.test", apiKey: "k", fetch: fake.fetch, sleep });
    await client.request("GET", "/x");
    expect(delays).toEqual([3_000]);
  });
});
