// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// The page-view beacon must cost the visitor nothing — 2026-09-18 incident.
//
// Cloud Run logged 504s on POST /api/v1/pageview while the backend was
// saturated. The beacon was already fire-and-forget on the client, so no page
// was ever blocked by it — but each call held a proxy socket for as long as the
// BFF would wait (120 s at the time), against a request whose entire value is
// one row in a counter table.
//
// These tests pin the three properties that make it harmless, so that a future
// "let me await this so I can log failures" reverts loudly:
//   1. it never throws, whatever the network does
//   2. it returns immediately — it does not await the response
//   3. it carries its own deadline
import fs from "node:fs";
import path from "node:path";

import { describe, it, expect, vi, afterEach } from "vitest";

import { sendPageView } from "../utils/analytics";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the page-view beacon", () => {
  it("does not throw when the request fails", () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    expect(() => sendPageView("/seamount/4272884")).not.toThrow();
  });

  it("does not throw when the request times out", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(Object.assign(new Error("aborted"), { name: "TimeoutError" })),
    );
    expect(() => sendPageView("/")).not.toThrow();
  });

  it("returns before the response does", async () => {
    // A fetch that never settles. If sendPageView awaited it, this test would
    // hang rather than fail — so the assertion is that we get here at all.
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    const started = Date.now();
    sendPageView("/vent/12");
    expect(Date.now() - started).toBeLessThan(50);
  });

  it("sends its own deadline with the request", () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);

    sendPageView("/layer/seamounts");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0][1];
    expect(init.signal, "no AbortSignal — the beacon can outlive the page view").toBeDefined();
    expect(init.keepalive).toBe(true);
    expect(init.method).toBe("POST");
  });

  it("aborts within a few seconds, not minutes", async () => {
    // ⛔ The number matters: a deadline longer than the BFF's own (20 s) would
    // put the beacon back in the business of holding proxy sockets open.
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);

    sendPageView("/");
    const signal: AbortSignal = fetchMock.mock.calls[0][1].signal;

    await new Promise((r) => setTimeout(r, 3100));
    expect(signal.aborted, "the beacon's own timeout never fired").toBe(true);
  }, 10_000);

  it("swallows the rejection at the call site", () => {
    // ⚠️ A SHAPE test, and deliberately so. Deleting the `.catch(() => {})`
    // produced ZERO reds across every behavioural test in this file (sabotage,
    // 2026-09-18): a rejected promise nobody handles does not throw at the call
    // site, and neither jsdom nor vitest surfaced the unhandled rejection where
    // an assertion could see it. Rather than leave a guard that cannot fail,
    // this one reads the source — the same trade-off, for the same reason, as
    // test_the_lock_release_path_does_not_await on the backend.
    const src = fs.readFileSync(
      path.resolve(process.cwd(), "src/utils/analytics.ts"), "utf8");
    const call = src.slice(src.indexOf("export function sendPageView"));
    expect(/\.catch\(/.test(call.slice(0, 600)), "sendPageView no longer swallows its own failure").toBe(true);
  });

  it("posts to the single-prefix path", () => {
    // Half of the same incident: /api/api/v1/... reached the backend anyway,
    // so nothing looked broken until Googlebot crawled the literal URL.
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);

    sendPageView("/");

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/api/v1/pageview");
    expect(url).not.toContain("/api/api/");
  });
});
