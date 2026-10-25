import { describe, expect, it } from "vitest";
import { LedgerClient, parseRetryAfter } from "../src/client";
import { fakeFetch, json, recordingSleep } from "./helpers/fake-fetch";

const NOW = Date.parse("2026-10-20T12:00:00Z");

describe("parseRetryAfter", () => {
  it("parses delay-seconds", () => {
    expect(parseRetryAfter("3", NOW)).toBe(3000);
    expect(parseRetryAfter(" 0 ", NOW)).toBe(0);
  });

  it("parses HTTP-dates relative to now", () => {
    expect(parseRetryAfter("Tue, 20 Oct 2026 12:00:07 GMT", NOW)).toBe(7000);
  });

  it("treats past dates as zero and junk as absent", () => {
    expect(parseRetryAfter("Tue, 20 Oct 2026 11:00:00 GMT", NOW)).toBe(0);
    expect(parseRetryAfter("soon", NOW)).toBeUndefined();
    expect(parseRetryAfter("-5", NOW)).toBeUndefined();
    expect(parseRetryAfter(null, NOW)).toBeUndefined();
  });
});

describe("Retry-After handling", () => {
  function setup(...responses: Parameters<typeof fakeFetch>) {
    const fake = fakeFetch(...responses);
    const { sleep, delays } = recordingSleep();
    const client = new LedgerClient({
      baseUrl: "https://api.ledger.test",
      apiKey: "k",
      fetch: fake.fetch,
      sleep,
      now: () => NOW,
      maxRetryDelayMs: 10_000,
    });
    return { client, delays, fake };
  }

  it("waits as long as the server asks on 429", async () => {
    const { client, delays } = setup(json(429, {}, { "Retry-After": "2" }), json(200, { ok: 1 }));
    await expect(client.request("GET", "/x")).resolves.toEqual({ ok: 1 });
    expect(delays).toEqual([2000]);
  });

  it("honours HTTP-date values on 503", async () => {
    const { client, delays } = setup(json(503, {}, { "Retry-After": "Tue, 20 Oct 2026 12:00:04 GMT" }), json(200, {}));
    await client.request("GET", "/x");
    expect(delays).toEqual([4000]);
  });

  it("caps server-requested waits at maxRetryDelayMs", async () => {
    const { client, delays } = setup(json(429, {}, { "Retry-After": "3600" }), json(200, {}));
    await client.request("GET", "/x");
    expect(delays).toEqual([10_000]);
  });

  it("falls back to exponential backoff without a usable header", async () => {
    const { client, delays } = setup(json(429, {}, { "Retry-After": "later" }), json(503, {}), json(200, {}));
    await client.request("GET", "/x");
    expect(delays).toEqual([250, 500]);
  });
});
