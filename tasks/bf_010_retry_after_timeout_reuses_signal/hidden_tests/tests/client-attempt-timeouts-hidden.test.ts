import { getEventListeners } from "node:events";
import { describe, expect, it } from "vitest";
import { LedgerClient } from "../src/client";
import { CancelledError, NetworkError, TimeoutError } from "../src/errors";
import { recordingSleep } from "./helpers/fake-fetch";

type Step = "hang" | "network-error" | (() => Response);

interface Call {
  url: string;
  signal: AbortSignal;
  abortedAtCall: boolean;
}

/**
 * Behaves like the real fetch with respect to abort signals: an already
 * aborted signal rejects immediately, and aborting rejects an in-flight call.
 */
function abortableFetch(...steps: Step[]) {
  const calls: Call[] = [];
  const waiters = new Map<number, () => void>();
  const impl = (input: string | URL | Request, init: RequestInit = {}) => {
    const signal = init.signal as AbortSignal;
    calls.push({ url: String(input), signal, abortedAtCall: signal.aborted });
    waiters.get(calls.length)?.();
    if (signal.aborted) return Promise.reject(new DOMException("This operation was aborted", "AbortError"));
    const step = steps.shift();
    if (step === undefined) return Promise.reject(new Error(`unexpected request to ${String(input)}`));
    if (step === "network-error") return Promise.reject(new TypeError("fetch failed"));
    if (step === "hang") {
      return new Promise<Response>((_, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("This operation was aborted", "AbortError")));
      });
    }
    return Promise.resolve(step());
  };
  /** Resolves when the n-th call (1-based) reaches fetch. */
  const nthCall = (n: number) =>
    new Promise<void>((resolve) => {
      if (calls.length >= n) resolve();
      else waiters.set(n, resolve);
    });
  return { fetch: impl as typeof fetch, calls, nthCall };
}

const ok = (body: unknown) => () =>
  new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const unavailable = () => new Response("{}", { status: 503, headers: { "Content-Type": "application/json" } });

function makeClient(fetchImpl: typeof fetch, timeoutMs = 20, maxRetries = 2) {
  const { sleep, delays } = recordingSleep();
  const client = new LedgerClient({ baseUrl: "https://api.ledger.test", apiKey: "k", fetch: fetchImpl, sleep, timeoutMs, maxRetries });
  return { client, delays };
}

describe("retries after an attempt times out", () => {
  it("retries a timed-out attempt and returns the next response", async () => {
    const fake = abortableFetch("hang", ok({ id: "inv_7" }));
    const { client } = makeClient(fake.fetch);
    await expect(client.request("GET", "/invoices/inv_7")).resolves.toEqual({ id: "inv_7" });
    expect(fake.calls).toHaveLength(2);
  });

  it("gives every attempt its own signal that is not already aborted", async () => {
    const fake = abortableFetch("hang", "hang", ok({ done: true }));
    const { client } = makeClient(fake.fetch);
    await expect(client.request("GET", "/reports/slow-then-ok")).resolves.toEqual({ done: true });
    expect(fake.calls.map((c) => c.abortedAtCall)).toEqual([false, false, false]);
    expect(new Set(fake.calls.map((c) => c.signal)).size).toBe(3);
  });

  it("keeps normal backoff when a timeout is followed by a retryable status", async () => {
    const fake = abortableFetch("hang", unavailable, ok({ n: 1 }));
    const { client, delays } = makeClient(fake.fetch);
    await expect(client.request("GET", "/x")).resolves.toEqual({ n: 1 });
    expect(delays).toEqual([250, 500]);
  });

  it("reports a timeout only after every attempt was really sent", async () => {
    const fake = abortableFetch("hang", "hang", "hang");
    const { client } = makeClient(fake.fetch);
    await expect(client.request("GET", "/x")).rejects.toBeInstanceOf(TimeoutError);
    expect(fake.calls).toHaveLength(3);
    expect(fake.calls.some((c) => c.abortedAtCall)).toBe(false);
  });

  it("classifies a network failure after a timeout as a network error", async () => {
    const fake = abortableFetch("hang", "network-error");
    const { client } = makeClient(fake.fetch, 20, 1);
    await expect(client.request("GET", "/x")).rejects.toBeInstanceOf(NetworkError);
  });

  it("lets the caller cancel a retry that follows a timeout", async () => {
    const fake = abortableFetch("hang", "hang", ok({}));
    const { client, delays } = makeClient(fake.fetch, 20, 2);
    const caller = new AbortController();
    const second = fake.nthCall(2);
    const pending = client.request("GET", "/x", { signal: caller.signal });
    await second;
    caller.abort();
    expect(fake.calls[1]!.signal.aborted).toBe(true);
    await expect(pending).rejects.toBeInstanceOf(CancelledError);
    expect(fake.calls).toHaveLength(2);
    expect(delays).toEqual([250]);
  });
});

describe("caller cancellation guards", () => {
  it("cancels the first attempt immediately without retrying", async () => {
    const fake = abortableFetch("hang", ok({}));
    const { client, delays } = makeClient(fake.fetch, 60_000);
    const caller = new AbortController();
    const first = fake.nthCall(1);
    const pending = client.request("GET", "/x", { signal: caller.signal });
    await first;
    caller.abort();
    expect(fake.calls[0]!.signal.aborted).toBe(true);
    await expect(pending).rejects.toBeInstanceOf(CancelledError);
    expect(fake.calls).toHaveLength(1);
    expect(delays).toEqual([]);
  });

  it("does not call fetch when the signal is already aborted", async () => {
    const fake = abortableFetch(ok({}));
    const { client } = makeClient(fake.fetch);
    const caller = new AbortController();
    caller.abort();
    await expect(client.request("GET", "/x", { signal: caller.signal })).rejects.toBeInstanceOf(CancelledError);
    expect(fake.calls).toHaveLength(0);
  });

  it("removes its abort listeners from the caller's signal when done", async () => {
    const fake = abortableFetch(unavailable, unavailable, ok({ fine: true }));
    const { client } = makeClient(fake.fetch);
    const caller = new AbortController();
    await expect(client.request("GET", "/x", { signal: caller.signal })).resolves.toEqual({ fine: true });
    expect(getEventListeners(caller.signal, "abort")).toHaveLength(0);
  });

  it("still times out a single slow attempt", async () => {
    const fake = abortableFetch("hang");
    const { client } = makeClient(fake.fetch, 20, 0);
    await expect(client.request("GET", "/x")).rejects.toBeInstanceOf(TimeoutError);
  });
});
