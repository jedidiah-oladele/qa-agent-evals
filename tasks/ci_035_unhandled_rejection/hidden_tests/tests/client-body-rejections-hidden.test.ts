import { describe, expect, it } from "vitest";
import { LedgerClient } from "../src/client";
import { ApiError } from "../src/errors";
import { fakeFetch, json, recordingSleep } from "./helpers/fake-fetch";

/** Run `fn` and collect every promise rejection nobody handled while it ran. */
async function unhandledDuring(fn: () => Promise<unknown>): Promise<unknown[]> {
  const seen: unknown[] = [];
  const listener = (reason: unknown) => {
    seen.push(reason);
  };
  process.on("unhandledRejection", listener);
  try {
    await fn();
    // Node reports unhandled rejections once the microtask queue has drained.
    await new Promise((resolve) => setTimeout(resolve, 25));
  } finally {
    process.off("unhandledRejection", listener);
  }
  return seen;
}

function setup(...responders: Parameters<typeof fakeFetch>) {
  const fake = fakeFetch(...responders);
  const { sleep, delays } = recordingSleep();
  const client = new LedgerClient({ baseUrl: "https://api.ledger.test", apiKey: "k", fetch: fake.fetch, sleep });
  return { client, fake, delays };
}

const page = (status: number, text: string, statusText = "") => () =>
  new Response(text, { status, statusText, headers: { "Content-Type": "text/html" } });

describe("retried responses with unreadable bodies", () => {
  it("leaves no unhandled rejection when retrying an HTML gateway page", async () => {
    const { client } = setup(page(502, "<html>Bad Gateway</html>", "Bad Gateway"), json(200, { id: "inv_42" }));
    const seen = await unhandledDuring(async () => {
      await expect(client.request("GET", "/invoices/inv_42")).resolves.toEqual({ id: "inv_42" });
    });
    expect(seen).toEqual([]);
  });

  it("leaves no unhandled rejection when retrying an empty 503 body", async () => {
    const { client } = setup(() => new Response("", { status: 503 }), json(200, { ok: true }));
    const seen = await unhandledDuring(async () => {
      await expect(client.request("GET", "/x")).resolves.toEqual({ ok: true });
    });
    expect(seen).toEqual([]);
  });

  it("leaves no unhandled rejection when a plain-text 429 is retried", async () => {
    const tooMany = () =>
      new Response("Too Many Requests", { status: 429, headers: { "Retry-After": "1", "Content-Type": "text/plain" } });
    const { client, delays } = setup(tooMany, json(200, { ok: true }));
    const seen = await unhandledDuring(async () => {
      await expect(client.request("GET", "/x")).resolves.toEqual({ ok: true });
    });
    expect(seen).toEqual([]);
    expect(delays).toEqual([1000]);
  });

  it("reports the last status line, without stray rejections, once retries run out", async () => {
    const gateway = page(502, "<html>Bad Gateway</html>", "Bad Gateway");
    const { client, fake } = setup(gateway, gateway, gateway);
    let error: unknown;
    const seen = await unhandledDuring(async () => {
      error = await client.request("GET", "/x").catch((e) => e);
    });
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 502, code: "http_error", message: "502 Bad Gateway" });
    expect(fake.calls).toHaveLength(3);
    expect(seen).toEqual([]);
  });
});

describe("response body guards", () => {
  it("still rejects a successful response whose body is not JSON", async () => {
    const { client } = setup(page(200, "<html>maintenance</html>"));
    await expect(client.request("GET", "/x")).rejects.toThrow();
  });

  it("maps JSON error bodies to ApiError", async () => {
    const { client } = setup(json(409, { error: { code: "already_paid", message: "Invoice is paid" } }));
    await expect(client.request("POST", "/invoices/1/void")).rejects.toMatchObject({
      status: 409,
      code: "already_paid",
      message: "Invoice is paid",
    });
  });

  it("parses JSON bodies of successful responses", async () => {
    const { client } = setup(json(201, { id: "inv_9", total_minor: 1250 }));
    await expect(client.request("POST", "/invoices", { body: {} })).resolves.toEqual({ id: "inv_9", total_minor: 1250 });
  });
});
