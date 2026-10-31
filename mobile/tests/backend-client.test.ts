import assert from "node:assert/strict";
import test from "node:test";
import {
  ApiError,
  BackendClient,
  fromServer,
  type RemoteAssessment,
} from "../src/api/backend-client";
import { IdentityStore } from "../src/storage/identity-store";

const id = "11111111-1111-4111-8111-111111111111";

test("history exposes lightweight metadata and opening a retained upload never submits analysis", async () => {
  const requests: string[] = [];
  const dto = {
    ...remote(),
    title: "Living Room Review",
    status: "ready" as const,
    findings: [],
  };
  const client = new BackendClient(
    { baseUrl: "http://localhost:8000", getToken: async () => "account-token" },
    async () => {
      throw new Error("Browsing must not upload photos");
    },
    async (input, init) => {
      assert.equal(init?.method ?? "GET", "GET");
      assert.equal(
        new Headers(init?.headers).get("Authorization"),
        "Bearer account-token",
      );
      requests.push(String(input));
      if (String(input).includes("?cursor="))
        return Response.json({
          items: [
            {
              id,
              title: dto.title,
              created_at: dto.created_at,
              status: "ready",
              open_count: null,
              photo: dto.photo,
            },
          ],
          next_cursor: null,
        });
      return Response.json(dto);
    },
  );
  const page = await client.history("page+/=");
  assert.equal(page.items[0].title, "Living Room Review");
  assert.equal(page.items[0].openCount, null);
  assert.deepEqual(page.items[0].photo.remote, {
    assessmentId: id,
    photoId: "photo-id",
  });
  const opened = await client.open(id);
  assert.equal(opened.status, "failed");
  assert.match(opened.error!, /unfinished analysis/);
  assert.equal(opened.title, "Living Room Review");
  assert.equal(requests.length, 2);
  assert.match(requests[0], /cursor=page%2B%2F%3D/);
});

test("API invokes fetch without a client receiver, as required by browser fetch", async () => {
  let receiver: unknown;
  const client = new BackendClient(
    { baseUrl: "http://localhost:8000", getToken: async () => "" },
    async () => {},
    async function (this: unknown) {
      receiver = this;
      return Response.json({ error: { code: "not_found" } }, { status: 404 });
    },
  );

  assert.equal(await client.latest(), null);
  assert.equal(receiver, undefined);
});

function remote(): RemoteAssessment {
  return {
    id,
    created_at: "2026-10-28T01:00:00Z",
    status: "complete",
    attempts: 1,
    error: null,
    photo: { id: "photo-id", uploaded: true },
    profiles: ["Baby", "Pet"],
    summary: "Qualified summary.",
    findings: [
      {
        id: "finding-id",
        title: "Visible concern",
        category: "Trips",
        severity: "Medium",
        evidence: "Visible cable",
        recommendation: "Keep route clear",
        short_action: "Clear the path",
        uncertainty: "Usage unclear",
        status: "resolved",
        note: "User decision",
        follow_up: {
          kind: "text",
          question: "Used at night?",
          state: "available",
        },
        submissions: [],
      },
    ],
  };
}

test("server mapping updates findings while preserving unsent evidence and local photo access", () => {
  const cached = fromServer(remote());
  cached.photo.uri = "data:image/png;base64,local";
  cached.findings[0].submissions.push({
    id: "pending",
    kind: "review",
    status: "ready",
    attempts: 0,
    text: "My evidence",
  });
  const dto = remote();
  dto.findings[0].short_action = "Updated action";
  const mapped = fromServer(dto, cached);
  assert.equal(mapped.findings[0].shortAction, "Updated action");
  assert.equal(mapped.findings[0].status, "resolved");
  assert.equal(mapped.findings[0].note, "User decision");
  assert.equal(mapped.findings[0].submissions[0].text, "My evidence");
  assert.equal(mapped.photo.uri, cached.photo.uri);
  assert.deepEqual(mapped.photo.remote, {
    assessmentId: id,
    photoId: "photo-id",
  });
  assert.equal(mapped.summary, "Qualified summary.");
});

test("API sends bearer/device headers and uploads a stable assessment ID without a forced multipart content type", async () => {
  const requests: { url: string; init: RequestInit }[] = [];
  const client = new BackendClient(
    { baseUrl: "http://localhost:8000", getToken: async () => "demo-only" },
    async (form) => {
      form.append(
        "photo",
        new Blob(["test photo"], { type: "image/jpeg" }),
        "room.jpg",
      );
    },
    (async (url, init) => {
      requests.push({ url: String(url), init: init! });
      return Response.json(remote(), { status: 201 });
    }) as typeof fetch,
  );
  const local = { ...fromServer(remote()), serverSaved: false };
  const saved = await client.upload(local);
  assert.equal(saved.id, id);
  const headers = new Headers(requests[0].init.headers);
  assert.equal(headers.get("Authorization"), "Bearer demo-only");
  assert.equal(headers.get("X-Device-ID"), null);
  assert.equal(headers.has("Content-Type"), false);
  const form = requests[0].init.body as FormData;
  assert.equal(form.get("assessment_id"), id);
  assert.equal(form.get("profiles"), '["Baby","Pet"]');
  await client.upload(saved);
  assert.equal(
    requests.length,
    1,
    "retained server input is not uploaded again on retry",
  );
});

test("latest 404 means no assessment; auth and model failures are errors with no fixture fallback or automatic retry", async () => {
  let calls = 0;
  let status = 404;
  const client = new BackendClient(
    { baseUrl: "http://localhost:8000", getToken: async () => "" },
    async () => {},
    (async () => {
      calls += 1;
      return Response.json(
        { error: { message: "Explicit failure", code: "failure" } },
        { status },
      );
    }) as typeof fetch,
  );
  assert.equal(await client.latest(), null);
  status = 401;
  await assert.rejects(
    client.latest(),
    (error: unknown) => error instanceof ApiError && error.status === 401,
  );
  status = 502;
  await assert.rejects(
    client.analyze(fromServer(remote())),
    /Explicit failure/,
  );
  assert.equal(calls, 3);
});

test("submitted server evidence stays frozen and private photos are downloaded with scoped headers", async () => {
  const dto = remote();
  dto.findings[0].submissions.push({
    id: "submission",
    kind: "review",
    text: "Saved",
    photo: { id: "linked-photo", uploaded: true },
    status: "failed",
    attempts: 1,
    error: "Retry",
    feedback: null,
  });
  const assessment = fromServer(dto);
  assert.equal(assessment.findings[0].submissions[0].frozen, true);
  let requests = 0;
  const client = new BackendClient(
    { baseUrl: "http://localhost:8000", getToken: async () => "demo" },
    async () => {
      assert.fail("Saved evidence must not be uploaded again");
    },
    (async (_url, init) => {
      requests += 1;
      assert.equal(new Headers(init!.headers).get("X-Device-ID"), null);
      assert.equal(
        new Headers(init!.headers).get("Authorization"),
        "Bearer demo",
      );
      return new Response(new Uint8Array([255, 216, 0, 100, 255]));
    }) as typeof fetch,
  );
  await client.uploadSubmission(
    assessment,
    assessment.findings[0],
    assessment.findings[0].submissions[0],
  );
  assert.equal(requests, 0);
  const uri = await client.photoDataUrl({
    assessmentId: id,
    photoId: "photo-id",
  });
  assert.equal(
    uri,
    "data:image/jpeg;base64," +
      Buffer.from([255, 216, 0, 100, 255]).toString("base64"),
  );
});

test("identity is durable across clients, concurrent initialization shares one UUID, and failed writes do not publish a transient identity", async () => {
  let saved: string | null = null;
  let writes = 0;
  const identity = new IdentityStore(
    async () => saved,
    async (value) => {
      saved = value;
      writes += 1;
    },
    () => id,
  );
  assert.deepEqual(await Promise.all([identity.get(), identity.get()]), [
    id,
    id,
  ]);
  assert.equal(writes, 1);
  assert.equal(
    await new IdentityStore(
      async () => saved,
      async () => {},
      () => {
        throw new Error("must not regenerate");
      },
    ).get(),
    id,
  );
  let fail = true;
  const broken = new IdentityStore(
    async () => null,
    async () => {
      if (fail) throw new Error("disk full");
    },
    () => id,
  );
  await assert.rejects(broken.get(), /disk full/);
  fail = false;
  assert.equal(await broken.get(), id);
});
