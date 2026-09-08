import { describe, it, expect, vi } from "vitest";
import { fetchUpstream, BackendUnavailable } from "./upstream-fetch.js";

const json = (body, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

describe("fetchUpstream", () => {
  it("returns the body on 200, without retrying", async () => {
    const f = vi.fn().mockResolvedValue(json({ id: 7 }));
    expect(await fetchUpstream("u", { fetchImpl: f })).toEqual({ id: 7 });
    expect(f).toHaveBeenCalledTimes(1);
  });

  it.each([400, 404, 410, 422])("returns null on %i and does not retry", async (s) => {
    const f = vi.fn().mockResolvedValue(json(null, s));
    expect(await fetchUpstream("u", { fetchImpl: f })).toBeNull();
    expect(f).toHaveBeenCalledTimes(1);
  });

  it.each([502, 503])("retries once on %i and succeeds on the second try", async (s) => {
    const f = vi.fn()
      .mockResolvedValueOnce(json(null, s))
      .mockResolvedValueOnce(json({ id: 9 }));
    expect(await fetchUpstream("u", { fetchImpl: f, retryDelayMs: 1 })).toEqual({ id: 9 });
    expect(f).toHaveBeenCalledTimes(2);
  });

  it("throws BackendUnavailable when both tries return 503", async () => {
    const f = vi.fn().mockResolvedValue(json(null, 503));
    await expect(fetchUpstream("u", { fetchImpl: f, retryDelayMs: 1 }))
      .rejects.toBeInstanceOf(BackendUnavailable);
    expect(f).toHaveBeenCalledTimes(2);   // exactly twice: not once, not three times
  });

  it("does NOT retry a 500 — only 502 and 503 mean a proxy answered for the backend", async () => {
    const f = vi.fn().mockResolvedValue(json(null, 500));
    await expect(fetchUpstream("u", { fetchImpl: f, retryDelayMs: 1 }))
      .rejects.toBeInstanceOf(BackendUnavailable);
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("does NOT retry a network failure — nothing is listening, so waiting only delays the 503", async () => {
    const f = vi.fn().mockRejectedValue(new Error("ECONNREFUSED"));
    await expect(fetchUpstream("u", { fetchImpl: f, retryDelayMs: 1 }))
      .rejects.toBeInstanceOf(BackendUnavailable);
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("waits the retry delay before the second try", async () => {
    const seen = [];
    const t0 = Date.now();
    const f = vi.fn()
      .mockImplementationOnce(async () => { seen.push(Date.now() - t0); return json(null, 503); })
      .mockImplementationOnce(async () => { seen.push(Date.now() - t0); return json({ ok: 1 }); });
    await fetchUpstream("u", { fetchImpl: f, retryDelayMs: 60 });
    expect(seen[1] - seen[0]).toBeGreaterThanOrEqual(50);
  });
});
