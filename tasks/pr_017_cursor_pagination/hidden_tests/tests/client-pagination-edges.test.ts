import { describe, expect, it } from "vitest";
import { LedgerClient } from "../src/client";
import { ApiError } from "../src/errors";
import { fakeFetch, json, recordingSleep } from "./helpers/fake-fetch";

function setup(...responses: Parameters<typeof fakeFetch>) {
  const fake = fakeFetch(...responses);
  const { sleep, delays } = recordingSleep();
  const client = new LedgerClient({
    baseUrl: "https://api.ledger.test",
    apiKey: "secret-key",
    fetch: fake.fetch,
    sleep,
  });
  return { client, fake, delays };
}

async function drain<T>(iterable: AsyncIterable<T>): Promise<{ items: T[]; error: unknown }> {
  const items: T[] = [];
  try {
    for await (const item of iterable) items.push(item);
  } catch (error) {
    return { items, error };
  }
  return { items, error: undefined };
}

describe("paginate edge cases", () => {
  it("detects a cursor that comes back after other pages", async () => {
    const { client, fake } = setup(
      json(200, { data: [1], next_cursor: "cur_9f2c" }),
      json(200, { data: [2], next_cursor: "cur_a051" }),
      json(200, { data: [3], next_cursor: "cur_9f2c" }),
    );
    const { items, error } = await drain(client.paginate<number>("/invoices"));
    expect(error).toBeInstanceOf(ApiError);
    expect(items).toEqual([1, 2, 3]);
    expect(fake.calls).toHaveLength(3);
  });

  it("retries a throttled page like any other request", async () => {
    const { client, fake, delays } = setup(
      json(200, { data: ["a"], next_cursor: "p2" }),
      json(503, {}),
      json(200, { data: ["b"], next_cursor: null }),
    );
    const { items, error } = await drain(client.paginate<string>("/invoices"));
    expect(error).toBeUndefined();
    expect(items).toEqual(["a", "b"]);
    expect(delays).toEqual([250]);
    expect(fake.calls.map((c) => c.url)).toEqual([
      "https://api.ledger.test/invoices",
      "https://api.ledger.test/invoices?cursor=p2",
      "https://api.ledger.test/invoices?cursor=p2",
    ]);
  });

  it("sends the API key on every page request", async () => {
    const { client, fake } = setup(
      json(200, { data: [1], next_cursor: "p2" }),
      json(200, { data: [2], next_cursor: null }),
    );
    await drain(client.paginate("/invoices"));
    for (const call of fake.calls) {
      expect((call.init.headers as Record<string, string>).Authorization).toBe("Bearer secret-key");
    }
  });

  it("URL-encodes opaque cursors", async () => {
    const { client, fake } = setup(
      json(200, { data: [1], next_cursor: "eyJpZCI6NDJ9+/=" }),
      json(200, { data: [], next_cursor: null }),
    );
    await drain(client.paginate("/invoices", { status: "open" }));
    expect(fake.calls[1]?.url).toBe("https://api.ledger.test/invoices?status=open&cursor=eyJpZCI6NDJ9%2B%2F%3D");
  });

  it("replaces a caller-supplied starting cursor on later pages", async () => {
    const { client, fake } = setup(
      json(200, { data: [5], next_cursor: "after-5" }),
      json(200, { data: [6], next_cursor: null }),
    );
    const { items } = await drain(client.paginate<number>("/invoices", { cursor: "resume-4", limit: 1 }));
    expect(items).toEqual([5, 6]);
    expect(fake.calls.map((c) => c.url)).toEqual([
      "https://api.ledger.test/invoices?cursor=resume-4&limit=1",
      "https://api.ledger.test/invoices?cursor=after-5&limit=1",
    ]);
  });

  it("yields earlier items before surfacing an error from a later page", async () => {
    const { client } = setup(
      json(200, { data: [1, 2], next_cursor: "p2" }),
      json(404, { error: { code: "gone", message: "cursor expired" } }),
    );
    const { items, error } = await drain(client.paginate<number>("/invoices"));
    expect(items).toEqual([1, 2]);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(404);
  });

  it("does not request the next page when the consumer stops at a page boundary", async () => {
    const { client, fake } = setup(json(200, { data: ["a", "b"], next_cursor: "p2" }));
    const seen: string[] = [];
    for await (const item of client.paginate<string>("/invoices")) {
      seen.push(item);
      if (seen.length === 2) break;
    }
    expect(seen).toEqual(["a", "b"]);
    expect(fake.calls).toHaveLength(1);
  });

  it("makes a single request for a one-page collection", async () => {
    const { client, fake } = setup(json(200, { data: [7, 8, 9], next_cursor: null }));
    const { items } = await drain(client.paginate<number>("/invoices"));
    expect(items).toEqual([7, 8, 9]);
    expect(fake.calls).toHaveLength(1);
  });
});
