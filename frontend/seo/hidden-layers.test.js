import { describe, it, expect } from "vitest";
import {
  parseHiddenLayers, hiddenLayersMetaTag, injectHiddenLayersMeta, HIDDEN_LAYERS_META_NAME,
} from "./hidden-layers.js";

const SHELL = '<!doctype html>\n<html>\n  <head>\n    <meta charset="UTF-8" />\n  </head>\n<body></body></html>';

describe("parseHiddenLayers", () => {
  it("splits, trims, drops empties, dedups, keeps only [a-z0-9-]+", () => {
    expect(parseHiddenLayers(" a-b , ,c1,a-b,UPPER,x y,<b>,\"q\"")).toEqual(["a-b", "c1"]);
  });
  it.each([undefined, null, "", " , ,"])("gives [] for %j", (v) => {
    expect(parseHiddenLayers(v)).toEqual([]);
  });
});

describe("injectHiddenLayersMeta", () => {
  it("returns the HTML untouched when nothing is hidden (byte-identical)", () => {
    expect(injectHiddenLayersMeta(SHELL, [])).toBe(SHELL);
  });
  it("inserts exactly one meta tag right after <head>", () => {
    const out = injectHiddenLayersMeta(SHELL, ["a-b", "c1"]);
    expect(out).toContain(`<head>\n  <meta name="${HIDDEN_LAYERS_META_NAME}" content="a-b,c1" />`);
    expect(out.split(HIDDEN_LAYERS_META_NAME).length - 1).toBe(1);
    expect(out.replace(/\n  <meta name="abyssal-hidden-layers"[^>]*\/>/, "")).toBe(SHELL);
  });
  it("leaves HTML with no <head> alone", () => {
    expect(injectHiddenLayersMeta("<p>x</p>", ["a"])).toBe("<p>x</p>");
  });
  it("escapes the attribute even for hostile input reaching the tag builder", () => {
    expect(hiddenLayersMetaTag(['a"><script>'])).toBe(
      '<meta name="abyssal-hidden-layers" content="a&quot;&gt;&lt;script&gt;" />');
  });
});
