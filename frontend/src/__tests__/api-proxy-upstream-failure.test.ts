// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// What the BFF must do when the VPS is slow or broken — 2026-09-18 incident.
//
// Googlebot crawling seamount pages got 503/504 bursts. The proxy set BOTH
// `timeout` (client-facing socket) and `proxyTimeout` (origin-facing socket) to
// 120 000 ms, four times Cloud Run's own 30 s request deadline, so Cloud Run
// always cut first and returned its OWN bare 504 — no body, no Retry-After.
// A crawler reads a bare 504 as "try again immediately"; it reads
// 503 + Retry-After as "come back in a minute".
//
// ⛔ The rule this guards (.claude/rules/subsystems/seo-ssr-sitemap.md):
// "missing" and "broken" must never share a code path.
//
//     upstream 400/404/410/422  → passed through unchanged  (about the request)
//     upstream 5xx / timeout    → 503 + Retry-After          (about us)
//
// A 404 that becomes a 503 tells Google to keep retrying a URL that will never
// exist; a timeout that becomes a 404 tells Google to drop a page that is fine.
// Both are de-indexing events across ~37,900 seamount URLs.
//
// These tests run a REAL upstream http server and a REAL express mount, because
// the thing under test is middleware behaviour, not a pure function.
import fs from "node:fs";
import http from "node:http";
import type { AddressInfo } from "node:net";
import path from "node:path";

import { describe, it, expect, beforeAll, afterAll } from "vitest";

// @ts-expect-error — plain JS module, no .d.ts; server-side code is not typed
// in this project and adding types for it is not what this test is about.
import { createApiProxy } from "../../seo/api-proxy.js";

const PROXY_SOURCE = path.resolve(process.cwd(), "seo/api-proxy.js");

const PROXY_TIMEOUT_MS = 300;        // short, so "slow" is slow within a test

let upstream: http.Server;
let bff: http.Server;
let base: string;

beforeAll(async () => {
  upstream = http.createServer((req, res) => {
    if (req.url?.startsWith("/v1/ok")) {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ ok: true }));
      return;
    }
    if (req.url?.startsWith("/v1/missing")) {
      res.writeHead(404, { "content-type": "application/json" });
      res.end(JSON.stringify({ detail: "Seamount 999 not found" }));
      return;
    }
    if (req.url?.startsWith("/v1/unprocessable")) {
      res.writeHead(422, { "content-type": "application/json" });
      res.end(JSON.stringify({ detail: "not an id" }));
      return;
    }
    if (req.url?.startsWith("/v1/boom")) {
      res.writeHead(500, { "content-type": "application/json" });
      res.end(JSON.stringify({ detail: "kaboom" }));
      return;
    }
    // /v1/slow — answer nothing at all, ever. This is what a saturated
    // single-process backend looked like during the incident.
  });
  await new Promise<void>((r) => upstream.listen(0, "127.0.0.1", r));
  const upstreamPort = (upstream.address() as AddressInfo).port;

  // ⚠️ The middleware is mounted directly on a bare http server rather than
  // through express. `pathRewrite: {"^/api": ""}` does the stripping either
  // way, and this keeps the test free of an untyped express import — what is
  // under test is the proxy's failure behaviour, not express.
  const proxy = createApiProxy({
    target: `http://127.0.0.1:${upstreamPort}`,
    apiKey: "test-key",
    proxyTimeoutMs: PROXY_TIMEOUT_MS,
  });
  bff = http.createServer((req, res) => {
    proxy(req, res, () => {
      res.statusCode = 500;
      res.end("middleware fell through — the proxy did not handle the request");
    });
  });
  await new Promise<void>((r) => bff.listen(0, "127.0.0.1", r));
  base = `http://127.0.0.1:${(bff.address() as AddressInfo).port}`;
});

afterAll(async () => {
  // The /v1/slow request leaves a socket open on purpose; without dropping it
  // first, close() waits for it and the hook times out.
  bff.closeAllConnections?.();
  upstream.closeAllConnections?.();
  await new Promise<void>((r) => bff.close(() => r()));
  await new Promise<void>((r) => upstream.close(() => r()));
});

describe("what the BFF answers when the origin misbehaves", () => {
  it("passes a healthy response through", async () => {
    const res = await fetch(`${base}/api/v1/ok`);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
  });

  it("turns an upstream 500 into 503 with Retry-After", async () => {
    const res = await fetch(`${base}/api/v1/boom`);
    expect(res.status).toBe(503);
    expect(res.headers.get("retry-after")).toBe("60");
  });

  it("turns a hanging upstream into 503 with Retry-After, not a hang", async () => {
    const started = Date.now();
    const res = await fetch(`${base}/api/v1/slow`);
    const elapsed = Date.now() - started;

    expect(res.status).toBe(503);
    expect(res.headers.get("retry-after")).toBe("60");
    // ⛔ The point is that WE answer, before anything above us gives up.
    expect(elapsed).toBeLessThan(PROXY_TIMEOUT_MS * 10);
  });

  it("writes the 503 even on a response object without Express helpers", async () => {
    // ⛔ Found by this harness on 2026-09-18: the error handler called
    // res.status()/.set()/.json(), which are Express's. On a plain node
    // ServerResponse it threw TypeError, nothing was written, and the client
    // hung until its own timeout — the exact 504 this file prevents. The
    // handler now writes either way, and this suite mounts the middleware on a
    // bare http server precisely so that path is the one under test.
    const res = await fetch(`${base}/api/v1/slow`);
    expect(res.status).toBe(503);
    expect(await res.json()).toMatchObject({ error: expect.any(String) });
  });

  it("leaves a 404 as a 404", async () => {
    // ⛔ The other half of the rule. A missing id must not be dressed up as an
    // outage — that is an instruction to Google to keep coming back forever.
    const res = await fetch(`${base}/api/v1/missing`);
    expect(res.status).toBe(404);
    expect(res.headers.get("retry-after")).toBeNull();
  });

  it("leaves a 422 as a 422", async () => {
    // Production caught this one the hard way in August: an id that cannot BE
    // an id was answered 503, i.e. "come back later" about a URL shape that can
    // never be valid.
    const res = await fetch(`${base}/api/v1/unprocessable`);
    expect(res.status).toBe(422);
  });
});

describe("the timeout is chosen against Cloud Run's deadline", () => {
  it("defaults to less than the 30s Cloud Run request timeout", async () => {
    const src = fs.readFileSync(PROXY_SOURCE, "utf8");
    const m = src.match(/proxyTimeoutMs\s*=\s*(\d+)/);
    expect(m, "no default proxyTimeoutMs found — it must be explicit").not.toBeNull();
    const ms = Number(m![1]);
    // Cloud Run is deployed with --timeout=30 (.github/workflows/deploy-gcp.yml).
    // Ours must fire first, or Cloud Run's bare 504 wins and our 503 never
    // reaches the client.
    expect(ms).toBeGreaterThan(0);
    expect(ms).toBeLessThan(30000);
  });

  it("does not set the client-facing `timeout` as well", async () => {
    // Setting both to the same value races two timers: reproduced locally with
    // a slow upstream and both at 500 ms, the request died with a raw
    // ECONNRESET instead of the 503 the error handler writes.
    const src = fs.readFileSync(PROXY_SOURCE, "utf8");
    expect(/^\s*timeout:/m.test(src)).toBe(false);
  });
});
