import { describe, expect, it } from "vitest";
import { LedgerClient } from "../src/client";
import { ApiError } from "../src/errors";
import { fakeFetch, json, recordingSleep } from "./helpers/fake-fetch";

function setup(...responses: Parameters<typeof fakeFetch>) {
  const fake = fakeFetch(...responses);
  const client = new LedgerClient({
    baseUrl: "https://api.ledger.test",
    apiKey: "k",
    fetch: fake.fetch,
    sleep: recordingSleep().sleep,
  });
  return { client, fake };
}

async function collect<T>(iterable: AsyncIterable<T>): Promise<T[]> {
  const items: T[] = [];
  for await (const item of iterable) items.push(item);
  return items;
}

describe("paginate", () => {
  it("follows cursors until next_cursor is null", async () => {
    const { client, fake } = setup(
      json(200, { data: [1, 2], next_cursor: "c2" }),
      json(200, { data: [3], next_cursor: "c3" }),
      json(200, { data: [4], next_cursor: null }),
    );
    expect(await collect(client.paginate<number>("/invoices", { status: "paid" }))).toEqual([1, 2, 3, 4]);
    expect(fake.calls.map((c) => c.url)).toEqual([
      "https://api.ledger.test/invoices?status=paid",
      "https://api.ledger.test/invoices?status=paid&cursor=c2",
      "https://api.ledger.test/invoices?status=paid&cursor=c3",
    ]);
  });

  it("fetches lazily", async () => {
    const { client, fake } = setup(json(200, { data: ["a", "b"], next_cursor: "n" }));
    for await (const item of client.paginate<string>("/invoices")) {
      expect(item).toBe("a");
      break;
    }
    expect(fake.calls).toHaveLength(1);
  });

  it("handles empty pages", async () => {
    const { client } = setup(json(200, { data: [], next_cursor: "x" }), json(200, { data: [9], next_cursor: null }));
    expect(await collect(client.paginate("/invoices"))).toEqual([9]);
  });

  it("detects a repeated cursor", async () => {
    const { client } = setup(
      json(200, { data: [1], next_cursor: "same" }),
      json(200, { data: [2], next_cursor: "same" }),
    );
    await expect(collect(client.paginate("/invoices"))).rejects.toBeInstanceOf(ApiError);
  });
});
