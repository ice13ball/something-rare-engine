// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMapStore } from "../store/mapStore";
import { EXPORT_LAYERS_FE, mapIdOf } from "../utils/exportLayers";
import type { LayerId } from "../types/layers";
import { aoiToParams } from "../utils/aoiGeometry";
import { FeedbackModal } from "./FeedbackModal";
import {
  ExportKeyModal,
  getStoredKey,
  setStoredKey,
  forgetKey,
} from "./ExportKeyModal";

const APIV2 = "https://apiv2.something-rare.com";
const BUNDLE_KEY = "__bundle__";

interface CountResult {
  count: number;
  capped: boolean;
  cap?: number;
}
interface CompositeCountResult {
  members: Array<{ id: string; count: number; cap: number; capped: boolean }>;
}
type CountState =
  | CountResult
  | CompositeCountResult
  | "loading"
  | "error"
  | null;

async function fetchCount(
  layerId: string,
  params: string,
  key: string,
): Promise<CountResult | CompositeCountResult> {
  const r = await fetch(`${APIV2}/v2/export/${layerId}/count?${params}`, {
    headers: { "X-API-Key": key },
  });
  if (!r.ok) throw new Error(String(r.status));
  return r.json();
}

interface DownloadCallbacks {
  onStart: () => void;
  onSuccess: () => void;
  onError: (msg: string) => void;
}

function bundleUrl(ids: string[], params: string, fmt: string): string {
  return `${APIV2}/v2/export/bundle?layers=${ids.join(",")}&${params}&format=${fmt}`;
}

function downloadBundle(
  ids: string[],
  params: string,
  fmt: string,
  key: string,
  callbacks: DownloadCallbacks,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  te: (k: string, opts?: Record<string, unknown>) => string,
): void {
  callbacks.onStart();
  fetch(bundleUrl(ids, params, fmt), { headers: { "X-API-Key": key } })
    .then((r) => {
      if (!r.ok) throw r.status; // throw numeric status for discriminated catch
      return r.blob();
    })
    .then((b) => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(b);
      a.download = "abyssal-export.zip";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 100);
      callbacks.onSuccess();
    })
    .catch((err: unknown) => {
      if (typeof err === "number") {
        if (err === 401) callbacks.onError(te("err401"));
        else if (err === 403) callbacks.onError(te("err403"));
        else if (err === 429) callbacks.onError(te("err429"));
        else callbacks.onError(te("errFailed", { code: err }));
      } else {
        callbacks.onError(te("errNetwork"));
      }
    });
}

// Maps family string from the registry to an i18n key (camelCase).
const FAMILY_KEY: Record<string, string> = {
  "ISA & seabed":     "isaSeabed",
  "Life & geology":   "lifeGeology",
  "Sensors":          "sensors",
  "Infrastructure":   "infrastructure",
  "Carbon fields":    "carbonFields",
  "Ocean fields":     "oceanFields",
  "Land":             "land",
  "Arctic & carbon":  "arcticCarbon",
};

// Stable family groups (preserves first-seen order)
function groupByFamily(
  layers: typeof EXPORT_LAYERS_FE,
): { family: string; layers: typeof EXPORT_LAYERS_FE }[] {
  const seen = new Map<string, (typeof EXPORT_LAYERS_FE)[number][]>();
  for (const l of layers) {
    if (!seen.has(l.family)) seen.set(l.family, []);
    seen.get(l.family)!.push(l);
  }
  return Array.from(seen.entries()).map(([family, ls]) => ({ family, layers: ls }));
}

export function ExportPanel() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { t } = useTranslation("panels");
  const te = (k: string, opts?: Record<string, unknown>) => (t as any)(`export.${k}`, opts);
  const exportPanelOpen = useMapStore((s) => s.exportPanelOpen);
  const setExportPanelOpen = useMapStore((s) => s.setExportPanelOpen);
  const exportCheckedLayers = useMapStore((s) => s.exportCheckedLayers);
  const toggleExportLayer = useMapStore((s) => s.toggleExportLayer);
  const setExportCheckedLayers = useMapStore((s) => s.setExportCheckedLayers);
  const aoiSelection = useMapStore((s) => s.aoiSelection);
  const exportFormat = useMapStore((s) => s.exportFormat);
  const setExportFormat = useMapStore((s) => s.setExportFormat);
  const activeLayers = useMapStore((s) => s.activeLayers);

  // Filter export registry to layers currently enabled on the map, plus
  // always-available field exports (no natural per-AOI map toggle, e.g. bathymetry)
  const visibleLayers = useMemo(
    () =>
      EXPORT_LAYERS_FE.filter(
        (l) => l.alwaysAvailable || activeLayers.has(mapIdOf(l) as LayerId),
      ),
    [activeLayers],
  );

  // Recompute family groups from the filtered list
  const layerGroups = useMemo(() => groupByFamily(visibleLayers), [visibleLayers]);

  // Mirror localStorage key as React state so UI re-renders on key changes
  const [storedKey, setStoredKeyState] = useState<string>(() => getStoredKey());
  const [showKeyModal, setShowKeyModal] = useState(false);
  const [showFeedback, setShowFeedback] = useState(false);
  const [counts, setCounts] = useState<Record<string, CountState>>({});
  const [downloadErrors, setDownloadErrors] = useState<Record<string, string>>({});
  const [downloading, setDownloading] = useState<Record<string, boolean>>({});
  const [bundleCopied, setBundleCopied] = useState(false);

  // Stashed bundle download fn run after the user saves a key
  const pendingDownloadRef = useRef<(() => void) | null>(null);
  // Tracks which layer IDs have already been fetched for the current AOI+key
  const fetchedIdsRef = useRef<Set<string>>(new Set());

  // Reset counts, download errors + fetch-tracking whenever AOI or key changes
  useEffect(() => {
    fetchedIdsRef.current = new Set();
    setCounts({});
    setDownloadErrors({});
    setDownloading({});
  }, [aoiSelection, storedKey]);

  // Count EVERY visible layer for the current AOI (once key + AOI are set) so we
  // can disable layers that have no data in the selected area before download.
  useEffect(() => {
    if (!aoiSelection || !storedKey) return;
    const params = aoiToParams(aoiSelection);
    const toFetch = visibleLayers
      .map((l) => l.id)
      .filter((id) => !fetchedIdsRef.current.has(id));
    if (!toFetch.length) return;
    for (const id of toFetch) {
      fetchedIdsRef.current.add(id);
      setCounts((prev) => ({ ...prev, [id]: "loading" }));
      fetchCount(id, params, storedKey)
        .then((result) => setCounts((prev) => ({ ...prev, [id]: result })))
        .catch(() => setCounts((prev) => ({ ...prev, [id]: "error" })));
    }
  }, [visibleLayers, aoiSelection, storedKey]);

  // Only download layers that are both checked AND still visible (active on map).
  // MUST be above the early return below — all hooks run unconditionally (React rules-of-hooks).
  const visibleCheckedIds = useMemo(
    () => Array.from(exportCheckedLayers).filter((id) => visibleLayers.some((l) => l.id === id)),
    [exportCheckedLayers, visibleLayers],
  );

  if (!exportPanelOpen) return null;

  // ── Helpers ─────────────────────────────────────────────────────────────

  // true = has data, false = known-empty for this AOI, null = unknown (loading/
  // error/not-yet-counted). Only a definite `false` blocks a layer.
  function hasData(c: CountState): boolean | null {
    if (c == null || c === "loading" || c === "error") return null;
    if ("members" in c) return c.members.some((m) => (m.count ?? 0) > 0);
    return (c.count ?? 0) > 0;
  }

  // Checked AND visible AND not known-empty for the current AOI.
  const downloadableIds = visibleCheckedIds.filter(
    (id) => hasData(counts[id] ?? null) !== false,
  );

  const canDownload = downloadableIds.length > 0 && !!aoiSelection;

  // Layers a user can actually pick: visible and not known-empty for this AOI.
  const selectableIds = visibleLayers
    .map((l) => l.id)
    .filter((id) => hasData(counts[id] ?? null) !== false);
  const allSelected =
    selectableIds.length > 0 && selectableIds.every((id) => exportCheckedLayers.has(id));

  function handleSelectAll() {
    setExportCheckedLayers(allSelected ? [] : selectableIds);
  }

  // ── Handlers ────────────────────────────────────────────────────────────

  function handleBundleDownload() {
    if (!aoiSelection || downloadableIds.length === 0) return;
    const ids = downloadableIds;
    const params = aoiToParams(aoiSelection);
    const key = getStoredKey();

    const callbacks: DownloadCallbacks = {
      onStart: () => {
        setDownloadErrors((prev) => {
          const next = { ...prev };
          delete next[BUNDLE_KEY];
          return next;
        });
        setDownloading((prev) => ({ ...prev, [BUNDLE_KEY]: true }));
      },
      onSuccess: () => {
        setDownloading((prev) => {
          const next = { ...prev };
          delete next[BUNDLE_KEY];
          return next;
        });
      },
      onError: (msg: string) => {
        setDownloadErrors((prev) => ({ ...prev, [BUNDLE_KEY]: msg }));
        setDownloading((prev) => {
          const next = { ...prev };
          delete next[BUNDLE_KEY];
          return next;
        });
      },
    };

    if (!key) {
      // Stash the bundle download (capture ids snapshot), show key modal
      pendingDownloadRef.current = () =>
        downloadBundle(ids, params, exportFormat, getStoredKey(), callbacks, te);
      setShowKeyModal(true);
    } else {
      downloadBundle(ids, params, exportFormat, key, callbacks, te);
    }
  }

  function handleKeySaved(k: string) {
    setStoredKey(k);          // persist to localStorage
    setStoredKeyState(k);     // update React state so UI reflects key
    setShowKeyModal(false);
    if (pendingDownloadRef.current) {
      pendingDownloadRef.current();
      pendingDownloadRef.current = null;
    }
  }

  function handleForgetKey() {
    forgetKey();
    setStoredKeyState("");
    setCounts({});
    fetchedIdsRef.current = new Set();
  }

  function handleBundleCopyCurl() {
    if (!aoiSelection || downloadableIds.length === 0) return;
    const ids = downloadableIds;
    const params = aoiToParams(aoiSelection);
    const url = bundleUrl(ids, params, exportFormat);
    const cmd = `curl -H 'X-API-Key: ${storedKey || "<your key>"}' '${url}' -o abyssal-export.zip`;
    navigator.clipboard.writeText(cmd).then(() => {
      setBundleCopied(true);
      setTimeout(() => setBundleCopied(false), 2000);
    });
  }

  // ── AOI label (discriminated-union narrowing) ────────────────────────────
  const aoiLabel = !aoiSelection
    ? null
    : aoiSelection.mode === "box"
      ? te("aoiBox")
      : aoiSelection.mode === "polygon"
        ? te("aoiPolygon")
        : aoiSelection.mode === "hexes"
          ? `${aoiSelection.cellIds.length} ${aoiSelection.cellIds.length === 1 ? te("hexCell") : te("hexCells")}`
          : te("aoiCustom");

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <>
      {/* Panel — fixed right side, pointer-events limited to the panel itself */}
      <div className="fixed right-4 top-20 z-overlay w-80 max-h-[calc(100vh-6rem)] flex flex-col bg-[#0d1117] border border-white/10 rounded-xl shadow-2xl pointer-events-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 shrink-0">
          <span className="text-white/90 text-xs font-semibold uppercase tracking-wider">
            {te("title")}
          </span>
          <div className="flex items-center gap-2">
            {storedKey && (
              <button
                onClick={handleForgetKey}
                className="text-white/50 hover:text-red-400 text-[10px] font-mono transition-colors"
                title="Remove stored API key from this browser"
              >
                {te("forgetKey")}
              </button>
            )}
            <button
              onClick={() => setExportPanelOpen(false)}
              className="text-white/60 hover:text-white text-xl leading-none ml-1"
              aria-label="Close export panel"
            >
              ×
            </button>
          </div>
        </div>

        {/* AOI / key status */}
        <div className="px-4 pt-3 pb-1 shrink-0 space-y-0.5">
          {aoiLabel ? (
            <p className="text-white/60 text-[10px] font-mono">
              {te("aoiLabel")} {aoiLabel}
            </p>
          ) : (
            <p className="text-amber-400/80 text-[10px]">
              {te("noAoiHint")}
            </p>
          )}
          {!storedKey && (
            <p className="text-white/30 text-[10px]">
              {te("noKeyHint")}
            </p>
          )}
        </div>

        {/* Select-all toggle — operates on selectable (visible, non-empty) layers */}
        {visibleLayers.length > 0 && (
          <div className="flex justify-end px-3 pt-1 shrink-0">
            <button
              onClick={handleSelectAll}
              disabled={selectableIds.length === 0}
              className="text-cyan-400/70 hover:text-cyan-300 disabled:text-white/20 disabled:cursor-not-allowed text-[10px] font-medium uppercase tracking-wide transition-colors"
            >
              {allSelected ? te("deselectAll") : te("selectAll")}
            </button>
          </div>
        )}

        {/* Layer list — grouped by family (only active map layers shown) */}
        <div className="overflow-y-auto custom-scrollbar flex-1 px-3 py-2 space-y-3">
          {visibleLayers.length === 0 && (
            <p className="text-white/35 text-[11px] px-1 py-4 text-center leading-relaxed">
              {te("noActiveLayers")}
            </p>
          )}
          {layerGroups.map(({ family, layers }) => (
            <div key={family}>
              <p className="text-white/30 text-[9px] font-semibold uppercase tracking-widest px-1 pb-1">
                {te(`families.${FAMILY_KEY[family] ?? family}`)}
              </p>
              <div className="space-y-1.5">
                {layers.map((layer) => {
                  const checked = exportCheckedLayers.has(layer.id);
                  const countState: CountState = counts[layer.id] ?? null;
                  const isComposite = layer.kind === "composite";
                  // Known-empty for this AOI (only once key + AOI are set + counted).
                  const isEmpty =
                    aoiSelection != null && !!storedKey && hasData(countState) === false;

                  return (
                    <div
                      key={layer.id}
                      className={`rounded-lg border px-3 py-2 space-y-1.5 transition-colors ${
                        isEmpty
                          ? "border-white/[0.05] bg-transparent opacity-45"
                          : checked
                            ? "border-white/20 bg-white/[0.05]"
                            : "border-white/[0.06] bg-white/[0.02]"
                      }`}
                    >
                      {/* Checkbox + label */}
                      <label
                        className={`flex items-start gap-2 ${
                          isEmpty ? "cursor-not-allowed" : "cursor-pointer"
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={checked && !isEmpty}
                          disabled={isEmpty}
                          onChange={() => toggleExportLayer(layer.id)}
                          className="mt-0.5 accent-cyan-400 shrink-0 disabled:opacity-40"
                        />
                        <div className="min-w-0">
                          <span className="text-white/85 text-xs font-medium">
                            {layer.label}
                          </span>
                          {isComposite && (
                            <span className="ml-1.5 text-cyan-400/70 text-[9px] font-mono uppercase">
                              composite
                            </span>
                          )}
                        </div>
                      </label>

                      {/* Availability / feature count — shown once AOI + key set */}
                      {aoiSelection && storedKey && (
                        <div className="pl-5 text-[10px] text-white/60 min-h-[14px]">
                          {countState === "loading" && (
                            <span className="animate-pulse text-white/40">
                              {te("counting")}
                            </span>
                          )}
                          {countState === "error" && (
                            <span className="text-red-400/70">
                              {te("countUnavailable")}
                            </span>
                          )}
                          {countState === null && (
                            <span className="text-white/20">—</span>
                          )}
                          {isEmpty && (
                            <span className="text-white/40">
                              {te("noDataInArea")}
                            </span>
                          )}
                          {!isEmpty &&
                            countState !== null &&
                            countState !== "loading" &&
                            countState !== "error" &&
                            ("members" in countState ? (
                              <span>
                                {te("featuresAcrossSources", {
                                  total: countState.members
                                    .reduce((s, m) => s + m.count, 0)
                                    .toLocaleString(),
                                  sources: countState.members.length,
                                })}
                                {countState.members.some((m) => m.capped) && (
                                  <span className="ml-1.5 text-amber-400/80">
                                    {te("cappedAt", {
                                      n: Math.max(
                                        ...countState.members.map((m) => m.cap),
                                      ).toLocaleString(),
                                    })}
                                  </span>
                                )}
                              </span>
                            ) : (
                              <span>
                                {(countState.count ?? 0).toLocaleString()}{" "}
                                {te("features")}
                                {countState.capped && countState.cap != null && (
                                  <span className="ml-1.5 text-amber-400/80">
                                    {te("cappedAt", {
                                      n: countState.cap.toLocaleString(),
                                    })}
                                  </span>
                                )}
                              </span>
                            ))}
                        </div>
                      )}

                      {/* Citation + verify-at-source link — only when checked */}
                      {checked && !isEmpty && (
                        <div className="pl-5 text-[9px] text-white/35 space-y-0.5">
                          {layer.citation && <p>{layer.citation}</p>}
                          <a
                            href={layer.sourceUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-cyan-400/60 hover:text-cyan-300 transition-colors"
                          >
                            {te("verifyAtSource")}
                          </a>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        {/* Bundle download area — format toggle + single ZIP + curl */}
        <div className="px-4 py-3 border-t border-white/[0.08] shrink-0 space-y-2">
          {/* Format toggle */}
          <div className="flex items-center gap-1.5">
            <span className="text-white/40 text-[10px] font-mono">{te("formatLabel")}</span>
            {(["geojson", "csv"] as const).map((fmt) => (
              <button
                key={fmt}
                onClick={() => setExportFormat(fmt)}
                className={`px-2 py-0.5 rounded text-[10px] font-mono transition-colors border ${
                  exportFormat === fmt
                    ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
                    : "bg-white/[0.06] text-white/50 hover:text-white/80 border-transparent"
                }`}
              >
                {fmt}
              </button>
            ))}
          </div>

          {/* Download ZIP + copy curl */}
          <div className="flex gap-1.5">
            <button
              onClick={handleBundleDownload}
              disabled={!canDownload}
              className="flex-1 px-2 py-1.5 rounded bg-cyan-500/15 hover:bg-cyan-500/25 disabled:opacity-30 text-cyan-300 text-[11px] font-mono transition-colors border border-cyan-500/20 disabled:cursor-not-allowed"
            >
              {downloading[BUNDLE_KEY] ? te("downloading") : te("downloadZip")}
            </button>
            <button
              onClick={handleBundleCopyCurl}
              disabled={!canDownload}
              className="px-2 py-1.5 rounded bg-white/[0.08] hover:bg-white/[0.15] disabled:opacity-30 text-white/70 text-[10px] font-mono transition-colors disabled:cursor-not-allowed"
              title="Copy curl command for bundle"
            >
              {bundleCopied ? te("copied") : te("curl")}
            </button>
          </div>

          {/* Bundle error */}
          {downloadErrors[BUNDLE_KEY] && (
            <p className="text-red-400/80 text-[10px]">
              ✗ {downloadErrors[BUNDLE_KEY]}
            </p>
          )}

          {/* Footer note */}
          <p className="text-[9px] text-white/25 leading-relaxed">
            {te("footer")}
          </p>
        </div>
      </div>

      {/* Key gate modal */}
      {showKeyModal && (
        <ExportKeyModal
          onSaved={handleKeySaved}
          onClose={() => {
            setShowKeyModal(false);
            pendingDownloadRef.current = null;
          }}
          onRequestKey={() => {
            setShowKeyModal(false);
            setShowFeedback(true);
          }}
        />
      )}

      {/* Feedback modal for key requests */}
      {showFeedback && (
        <FeedbackModal initialKind="api_key" onClose={() => setShowFeedback(false)} />
      )}
    </>
  );
}
