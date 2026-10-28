import assert from "node:assert/strict";
import test from "node:test";
import { BackendClient } from "../src/api/backend-client";

test("API and image requests obtain fresh credentials and reject late responses after disposal", async () => {
  let token = "first";
  const headers: Headers[] = [];
  let finish: ((response: Response) => void) | undefined;
  const client = new BackendClient(
    { baseUrl: "https://example.test", getToken: async () => token },
    async () => {},
    (async (_url, init) => {
      headers.push(new Headers(init?.headers));
      return new Response(null, { status: 404 });
    }) as typeof fetch,
  );
  await client.latest();
  token = "second";
  await client.latest();
  assert.equal(headers[0].get("Authorization"), "Bearer first");
  assert.equal(headers[1].get("Authorization"), "Bearer second");
  assert.equal(headers[1].has("X-Device-ID"), false);
  const late = new BackendClient(
    { baseUrl: "https://example.test", getToken: async () => token },
    async () => {},
    (() =>
      new Promise<Response>((resolve) => {
        finish = resolve;
      })) as typeof fetch,
  );
  const pending = late.latest();
  await new Promise((resolve) => setImmediate(resolve));
  late.dispose();
  finish!(new Response(null, { status: 404 }));
  await assert.rejects(pending);
});
