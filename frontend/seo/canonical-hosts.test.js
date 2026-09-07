import { describe, expect, it, vi } from "vitest";
import { forceHttpsMiddleware, wwwRedirectMiddleware, getCanonicalHosts, isAllowedHost } from "./canonical-hosts.js";

// Fake req/res, not supertest (not a project dependency) — these call the
// exported middleware functions directly, the same objects Express would
// build for a real request, and assert on what res.redirect was called with.
function fakeReq({ host, xfp, url = "/some/path" } = {}) {
  return {
    headers: { host, "x-forwarded-proto": xfp },
    url,
    protocol: "https",
  };
}
function fakeRes() {
  return { redirect: vi.fn() };
}

describe("open-redirect fix: unknown Host never redirects to itself", () => {
  it("Host: evil.com + X-Forwarded-Proto: http → no redirect to evil.com", () => {
    const req = fakeReq({ host: "evil.com", xfp: "http" });
    const res = fakeRes();
    const next = vi.fn();
    forceHttpsMiddleware(req, res, next);
    expect(res.redirect).not.toHaveBeenCalled();
    expect(next).toHaveBeenCalled();
  });

  it("Host: www.evil-example.com → no redirect to evil-example.com", () => {
    const req = fakeReq({ host: "www.evil-example.com" });
    const res = fakeRes();
    const next = vi.fn();
    wwwRedirectMiddleware(req, res, next);
    expect(res.redirect).not.toHaveBeenCalled();
    expect(next).toHaveBeenCalled();
  });
});

describe("legitimate behaviour survives", () => {
  it("Host: something-rare.com + X-Forwarded-Proto: http → still redirects to https://something-rare.com", () => {
    const req = fakeReq({ host: "something-rare.com", xfp: "http", url: "/foo?x=1" });
    const res = fakeRes();
    const next = vi.fn();
    forceHttpsMiddleware(req, res, next);
    expect(res.redirect).toHaveBeenCalledWith(301, "https://something-rare.com/foo?x=1");
    expect(next).not.toHaveBeenCalled();
  });

  it("Host: www.something-rare.com → still redirects to https://something-rare.com", () => {
    const req = fakeReq({ host: "www.something-rare.com", url: "/bar" });
    const res = fakeRes();
    const next = vi.fn();
    wwwRedirectMiddleware(req, res, next);
    expect(res.redirect).toHaveBeenCalledWith(301, "https://something-rare.com/bar");
    expect(next).not.toHaveBeenCalled();
  });

  it("is case-insensitive on Host, without stripping anything but the 'www.' prefix", () => {
    const req = fakeReq({ host: "WWW.Something-Rare.COM", xfp: "http", url: "/baz" });
    const res = fakeRes();
    const next = vi.fn();
    // Force-HTTPS must still fire on the mixed-case host.
    forceHttpsMiddleware(req, res, next);
    expect(res.redirect).toHaveBeenCalledWith(301, "https://WWW.Something-Rare.COM/baz");
  });
});

describe("CANONICAL_HOSTS env override", () => {
  it("getCanonicalHosts(env) honours a custom value verbatim, no built-in default mixed in", () => {
    const hosts = getCanonicalHosts({ CANONICAL_HOSTS: "example.test, www.example.test" });
    expect(hosts).toEqual(["example.test", "www.example.test"]);
    expect(isAllowedHost("something-rare.com", hosts)).toBe(false);
  });

  it("the middleware itself honours process.env.CANONICAL_HOSTS", () => {
    const original = process.env.CANONICAL_HOSTS;
    process.env.CANONICAL_HOSTS = "example.test,www.example.test";
    try {
      // The built-in default something-rare.com must NOT leak through once
      // CANONICAL_HOSTS is set — this Host is only legitimate under the default list.
      const reqDefault = fakeReq({ host: "www.something-rare.com", url: "/qux" });
      const resDefault = fakeRes();
      const nextDefault = vi.fn();
      wwwRedirectMiddleware(reqDefault, resDefault, nextDefault);
      expect(resDefault.redirect).not.toHaveBeenCalled();
      expect(nextDefault).toHaveBeenCalled();

      // The custom host IS honoured.
      const req = fakeReq({ host: "www.example.test", url: "/qux" });
      const res = fakeRes();
      const next = vi.fn();
      wwwRedirectMiddleware(req, res, next);
      expect(res.redirect).toHaveBeenCalledWith(301, "https://example.test/qux");
    } finally {
      process.env.CANONICAL_HOSTS = original;
    }
  });
});
