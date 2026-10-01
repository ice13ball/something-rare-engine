import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

const H1 = "svalbard-fjords-primary-production";
const H2 = "greenland-sea-poc-aoc2025";

function setMeta(content: string | null) {
  document.head.querySelectorAll('meta[name="abyssal-hidden-layers"]').forEach((m) => m.remove());
  if (content !== null) {
    const m = document.createElement("meta");
    m.setAttribute("name", "abyssal-hidden-layers");
    m.setAttribute("content", content);
    document.head.appendChild(m);
  }
}

// The meta is read once per page load, so each case loads fresh module instances.
async function load() {
  vi.resetModules();
  const hidden = await import("../utils/hiddenLayers");
  const cfg = await import("../utils/layerConfig");
  const store = await import("../store/mapStore");
  return { hidden, cfg, store };
}

const okResponse = (ids: string[]) => ({
  ok: true,
  json: async () => ids.map((id, i) => ({ id, order_idx: i, default_on: false, modes: ["ocean"] })),
});

beforeEach(() => { localStorage.clear(); });
afterEach(() => { setMeta(null); vi.unstubAllGlobals(); });

describe("parseHiddenLayers", () => {
  it("splits, trims, drops empties, dedups and rejects malformed ids", async () => {
    const { hidden } = await load();
    expect(hidden.parseHiddenLayers(" a-b , ,c1,a-b,UPPER,x y,<script>,\"q\" ")).toEqual(["a-b", "c1"]);
    expect(hidden.parseHiddenLayers("")).toEqual([]);
    expect(hidden.parseHiddenLayers(null)).toEqual([]);
  });
});

describe("with NO meta tag (byte-identical to before)", () => {
  it("keeps null = allow-all everywhere", async () => {
    setMeta(null);
    const { cfg, store } = await load();
    expect(cfg.initialEnabledIds()).toBeNull();
    expect(cfg.deriveEnabledIds(null)).toBeNull();
    expect(store.useMapStore.getState().enabledLayerIds).toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    const r = await cfg.fetchLayerConfig();
    expect(r.enabledIds).toBeNull();
    expect(r.config).toBe(cfg.LAYER_DEFAULTS);
  });

  it("an empty meta content behaves the same", async () => {
    setMeta("");
    const { cfg } = await load();
    expect(cfg.deriveEnabledIds(null)).toBeNull();
  });
});

describe("with hidden layers", () => {
  it("fresh fetch: hidden id removed even when the backend says enabled", async () => {
    setMeta(`${H1},${H2}`);
    const { cfg } = await load();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okResponse(["argo", H1, H2, "eez"])));
    const r = await cfg.fetchLayerConfig();
    expect([...r.enabledIds!].sort()).toEqual(["argo", "eez"]);
  });

  it("fetch failure: fallback is all known ids minus hidden, not null", async () => {
    setMeta(`${H1},${H2}`);
    const { cfg } = await load();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    const r = await cfg.fetchLayerConfig();
    expect(r.enabledIds).not.toBeNull();
    expect(r.enabledIds!.has(H1)).toBe(false);
    expect(r.enabledIds!.has(H2)).toBe(false);
    expect(r.enabledIds!.has("argo")).toBe(true);
    expect(r.enabledIds!.size).toBeGreaterThan(50);
  });

  it("non-ok response also falls back to known-minus-hidden", async () => {
    setMeta(H1);
    const { cfg } = await load();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => [] }));
    const r = await cfg.fetchLayerConfig();
    expect(r.enabledIds!.has(H1)).toBe(false);
    expect(r.enabledIds!.has("eez")).toBe(true);
  });

  it("localStorage cache path: a cache written before the layer was hidden is filtered", async () => {
    setMeta(H1);
    const { cfg } = await load();
    const data = ["argo", H1].map((id, i) => ({ id, order_idx: i, default_on: false, modes: ["ocean"] }));
    localStorage.setItem("abyssal_layer_config", JSON.stringify({ ts: Date.now(), data }));
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const r = await cfg.fetchLayerConfig();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect([...r.enabledIds!]).toEqual(["argo"]);
  });

  it("unknown ids in the list are ignored", async () => {
    setMeta("no-such-layer,argo");
    const { cfg } = await load();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okResponse(["argo", "eez"])));
    const r = await cfg.fetchLayerConfig();
    expect([...r.enabledIds!]).toEqual(["eez"]);
  });

  it("store starts gated, before /layer-config answers", async () => {
    setMeta(`${H1},${H2}`);
    const { store } = await load();
    const s = store.useMapStore.getState();
    expect(s.enabledLayerIds).not.toBeNull();
    expect(s.enabledLayerIds!.has(H1)).toBe(false);
    expect(s.activeLayers.has(H1 as never)).toBe(false);
  });

  it("share-link restore: a hidden id in `l` does not switch on, others do", async () => {
    setMeta(`${H1},${H2}`);
    const { store } = await load();
    const { decodeShareState, encodeShareState } = await import("../utils/shareState");
    const raw = (encodeShareState as (s: unknown) => string)({
      camera: { longitude: 0, latitude: 0, zoom: 3, pitch: 0, bearing: 0 },
      layers: ["argo", H1, H2],
      filters: {},
    });
    const decoded = decodeShareState(raw);
    expect(decoded?.layers).toEqual(expect.arrayContaining([H1, H2, "argo"]));
    // The boot path: resolveInitialLayers -> setActiveLayers.
    const { resolveInitialLayers } = await import("../components/map3d/shareBootstrap");
    store.useMapStore.getState().setActiveLayers(resolveInitialLayers(decoded, null, [])!);
    const active = store.useMapStore.getState().activeLayers as Set<string>;
    expect(active.has(H1)).toBe(false);
    expect(active.has(H2)).toBe(false);
    expect(active.has("argo")).toBe(true);
  });

  it("toggleLayer cannot turn a hidden layer on", async () => {
    setMeta(H1);
    const { store } = await load();
    store.useMapStore.getState().toggleLayer(H1 as never);
    expect((store.useMapStore.getState().activeLayers as Set<string>).has(H1)).toBe(false);
  });

  it("isLayerHidden reflects the meta (used to drop `p`/`o` picks of a hidden layer)", async () => {
    setMeta(H1);
    const { hidden } = await load();
    expect(hidden.isLayerHidden(H1)).toBe(true);
    expect(hidden.isLayerHidden(H2)).toBe(false);
  });
});
