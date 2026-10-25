import { describe, expect, it } from "vitest";
import { LedgerClient } from "../src/client";
import { fakeFetch, json, recordingSleep } from "./helpers/fake-fetch";

const BASE = "https://api.ledger.test/v1";

function makeClient(fetchImpl: typeof fetch = fakeFetch().fetch) {
  return new LedgerClient({ baseUrl: BASE, apiKey: "sk_test", fetch: fetchImpl, sleep: recordingSleep().sleep });
}

describe("query values with reserved characters", () => {
  const c = makeClient();

  it("encodes ampersands inside a value", () => {
    expect(c.buildUrl("/customers", { q: "Smith & Sons" })).toBe(`${BASE}/customers?q=Smith%20%26%20Sons`);
  });

  it("encodes plus signs so they are not read as spaces", () => {
    expect(c.buildUrl("/invoices", { reference: "C++ license" })).toBe(`${BASE}/invoices?reference=C%2B%2B%20license`);
  });

  it("encodes hash and question marks", () => {
    expect(c.buildUrl("/invoices", { reference: "#42?draft" })).toBe(`${BASE}/invoices?reference=%2342%3Fdraft`);
  });

  it("encodes equals signs, slashes and commas", () => {
    expect(c.buildUrl("/search", { filter: "a=b/c,d" })).toBe(`${BASE}/search?filter=a%3Db%2Fc%2Cd`);
  });

  it("encodes every element of an array value separately", () => {
    expect(c.buildUrl("/search", { tag: ["R&D", "ops/eu", "a+b"] })).toBe(
      `${BASE}/search?tag=R%26D&tag=ops%2Feu&tag=a%2Bb`,
    );
  });

  it("round-trips arbitrary values through a standard query parser", () => {
    const values = ["Smith & Sons", "C++", "50% off", "a=b&c=d", "#1", "x/y?z", "Zürich", "comma,separated", "  "];
    const url = new URL(c.buildUrl("/search", { q: values }));
    expect(url.pathname).toBe("/v1/search");
    expect(url.hash).toBe("");
    expect(url.searchParams.getAll("q")).toEqual(values);
    expect([...url.searchParams.keys()].every((k) => k === "q")).toBe(true);
  });
});

describe("requests built from queries", () => {
  it("sends the encoded customer filter when listing invoices", async () => {
    const fake = fakeFetch(json(200, { data: [], next_cursor: null }));
    await makeClient(fake.fetch).listInvoices({ customer: "Ben & Jerry+Co", status: "issued" });
    expect(fake.calls[0]!.url).toBe(`${BASE}/invoices?customer=Ben%20%26%20Jerry%2BCo&status=issued`);
  });

  it("encodes base64 cursors when following pages", async () => {
    const fake = fakeFetch(
      json(200, { data: [1], next_cursor: "eyJpZCI6MTJ9+/a==" }),
      json(200, { data: [2], next_cursor: null }),
    );
    const items: number[] = [];
    for await (const item of makeClient(fake.fetch).paginate<number>("/invoices")) items.push(item);
    expect(items).toEqual([1, 2]);
    expect(fake.calls[1]!.url).toBe(`${BASE}/invoices?cursor=eyJpZCI6MTJ9%2B%2Fa%3D%3D`);
  });
});

describe("query encoding guards", () => {
  const c = makeClient();

  it("percent-encodes spaces and non-ASCII characters", () => {
    expect(c.buildUrl("/customers", { city: "São Paulo" })).toBe(`${BASE}/customers?city=S%C3%A3o%20Paulo`);
  });

  it("encodes bracketed keys and keeps unreserved characters", () => {
    expect(c.buildUrl("/invoices", { "created[gte]": "2026-01-01", sort: "-created_at.desc~" })).toBe(
      `${BASE}/invoices?created%5Bgte%5D=2026-01-01&sort=-created_at.desc~`,
    );
  });

  it("skips null and undefined and stringifies numbers and booleans", () => {
    expect(c.buildUrl("/invoices", { limit: 25, paid: true, cursor: null, customer: undefined })).toBe(
      `${BASE}/invoices?limit=25&paid=true`,
    );
  });
});
