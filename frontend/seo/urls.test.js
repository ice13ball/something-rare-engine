import { describe, expect, it } from "vitest";
import { canonicalUrl, encodeSegment, normaliseUrl, SITE } from "./urls.js";

// The two families that were live-broken on 2026-08-23. These are not examples;
// they are the exact ids, and each assertion is the address the sitemap declares.
describe("the 11 URLs where the canonical and the sitemap disagreed", () => {
  it("keeps ':' raw, the way the sitemap has always emitted it", () => {
    expect(canonicalUrl("/river", "arcticgro:kolyma")).toBe(`${SITE}/river/arcticgro:kolyma`);
  });

  it("no longer over-encodes ':' to '%3A' (the /river direction)", () => {
    expect(normaliseUrl(`${SITE}/river/arcticgro%3Akolyma`)).toBe(`${SITE}/river/arcticgro:kolyma`);
  });

  it("no longer leaves a raw space in an href (the /report/chess: direction)", () => {
    expect(canonicalUrl("/report", "chess:Snake Pit")).toBe(`${SITE}/report/chess:Snake%20Pit`);
    expect(normaliseUrl(`${SITE}/report/chess:Snake Pit`)).toBe(`${SITE}/report/chess:Snake%20Pit`);
  });

  it("encodes '°' as UTF-8, matching the sitemap", () => {
    expect(canonicalUrl("/report", "chess:10°N - EPR")).toBe(`${SITE}/report/chess:10%C2%B0N%20-%20EPR`);
  });
});

// The sitemap encodes each <loc> with `new URL().href`. For the characters our
// ids actually contain, this encoder must agree with it byte for byte — that
// agreement IS the fix, so it is asserted rather than assumed.
describe("agreement with the sitemap's own encoder", () => {
  for (const id of [
    "arcticgro:kolyma", "arcticgro:yenisey",
    "chess:Snake Pit", "chess:Hydrate Ridge", "chess:10°N - EPR",
    "chess:Rodriguez Triple Junction", "chess:Santa Cruz Basin Whale Fall",
  ]) {
    it(`matches new URL() for "${id}"`, () => {
      expect(canonicalUrl("/report", id)).toBe(new URL(`${SITE}/report/${id}`).href);
    });
  }
});

// The brief asked what happens to an id containing a character neither of us
// thought of. Answered here rather than discovered in production.
describe("characters that are not ':' or a space", () => {
  it("keeps a '/' inside the id, instead of inventing a path separator", () => {
    expect(encodeSegment("a/b")).toBe("a%2Fb");
  });

  it("keeps a '#' inside the id, instead of inventing a fragment", () => {
    expect(encodeSegment("a#b")).toBe("a%23b");
    // new URL() would silently lose it — the reason this file does not use it.
    expect(new URL(`${SITE}/report/a#b`).pathname).toBe("/report/a");
  });

  it("keeps a '?' inside the id, instead of inventing a query", () => {
    expect(encodeSegment("a?b")).toBe("a%3Fb");
  });

  it("encodes a literal '%' once, not twice", () => {
    expect(encodeSegment("100%")).toBe("100%25");
    expect(normaliseUrl(`${SITE}/report/100%25`)).toBe(`${SITE}/report/100%25`);
  });

  it("percent-encodes non-Latin characters as UTF-8", () => {
    expect(encodeSegment("Река")).toBe("%D0%A0%D0%B5%D0%BA%D0%B0");
  });

  it("does not throw on a segment whose '%' is not a valid escape", () => {
    expect(() => normaliseUrl(`${SITE}/report/50%off`)).not.toThrow();
  });
});

describe("normaliseUrl", () => {
  it("is idempotent — applying it twice changes nothing", () => {
    const once = normaliseUrl(`${SITE}/report/chess:Snake Pit`);
    expect(normaliseUrl(once)).toBe(once);
  });

  it("preserves a query string and a fragment", () => {
    expect(normaliseUrl(`${SITE}/seamount?page=2`)).toBe(`${SITE}/seamount?page=2`);
    expect(normaliseUrl(`${SITE}/about#citation`)).toBe(`${SITE}/about#citation`);
  });

  it("leaves a non-URL string alone rather than throwing", () => {
    expect(normaliseUrl("not a url")).toBe("not a url");
  });
});
