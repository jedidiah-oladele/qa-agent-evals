export interface RecordedCall {
  url: string;
  init: RequestInit;
}

export type Responder = (call: RecordedCall) => Response | Promise<Response>;

/** A fetch replacement that answers from a queue of responders and records calls. */
export function fakeFetch(...responders: Responder[]) {
  const calls: RecordedCall[] = [];
  const impl = async (input: string | URL | Request, init: RequestInit = {}) => {
    const call = { url: String(input), init };
    calls.push(call);
    const responder = responders.shift();
    if (!responder) throw new Error(`unexpected request to ${call.url}`);
    return responder(call);
  };
  return { fetch: impl as typeof fetch, calls };
}

export function json(status: number, body: unknown, headers: Record<string, string> = {}): Responder {
  return () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json", ...headers },
    });
}

export function recordingSleep() {
  const delays: number[] = [];
  const sleep = async (ms: number) => {
    delays.push(ms);
  };
  return { sleep, delays };
}
