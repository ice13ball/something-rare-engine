// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect, useRef, useCallback, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { useMapStore } from "../../store/mapStore";
import type { LayerId } from "../../types/layers";
import { LocateIcon } from "../icons";
import { LAYER_TOOLTIPS_META, LAYER_LABEL_MAP, dashToCamel, type LayerTooltipMeta } from "./tooltips";

export interface CheckboxFilterDef {
  key: string;
  label: string;
  color: string;
  code?: string;
  dot?: boolean;
}

/**
 * Tiny "Reset filters" link shown inside an expanded filter section.
 * Renders only when `show` is true. Calls `onReset` once. Pattern matches the
 * AIS Live filter reset link (line ~1180) so the affordance is consistent.
 */
export function FilterResetLink({ show, onReset, label = "Reset filters" }: { show: boolean; onReset: () => void; label?: string }) {
  if (!show) return null;
  return (
    <button
      type="button"
      onClick={onReset}
      className="text-cyan-300 hover:text-cyan-200 text-[11px]"
    >
      {label}
    </button>
  );
}

export function CheckboxFilter({
  header,
  headerClassName = "text-white/60 text-[10px] font-mono uppercase tracking-[0.12em] pb-0.5",
  defs,
  activeSet,
  onToggle,
  clearLabel,
}: {
  header: string;
  headerClassName?: string;
  defs: readonly CheckboxFilterDef[];
  activeSet: Set<string>;
  onToggle: (key: string) => void;
  clearLabel?: string;
}) {
  const { t } = useTranslation(["panels", "common"]);
  return (
    <>
      <p className={headerClassName}>{header}</p>
      {defs.map(d => (
        <label key={d.key} className="flex items-center gap-2 py-0.5 cursor-pointer">
          <input
            type="checkbox"
            checked={activeSet.has(d.key)}
            onChange={() => onToggle(d.key)}
            className="w-3 h-3"
            style={{ accentColor: d.color }}
          />
          <span className="text-white/75 text-[13px] flex items-center gap-1.5">
            {d.code && (
              <span className="font-mono text-[13px] font-bold" style={{ color: d.color }}>{d.code}</span>
            )}
            {d.dot && (
              <span className="inline-block w-2 h-2 rounded-full flex-shrink-0" style={{ background: d.color }} />
            )}
            {d.label}
          </span>
        </label>
      ))}
      {activeSet.size > 0 && clearLabel && (
        <button
          onClick={() => defs.forEach(d => activeSet.has(d.key) && onToggle(d.key))}
          aria-label={t("common:tooltips.clearFilters")}
          className="mt-0.5 text-white/70 hover:text-white/80 text-[13px] transition-colors"
        >
          {clearLabel}
        </button>
      )}
    </>
  );
}

export function SubGroup({ label, storageKey, defaultExpanded = false, children }: {
  label: string;
  storageKey: string;
  defaultExpanded?: boolean;
  children: ReactNode;
}) {
  const { t } = useTranslation(["panels", "common"]);
  const [expanded, setExpanded] = useState<boolean>(() => {
    try {
      const raw = JSON.parse(localStorage.getItem("abyssal_subgroups") ?? "{}");
      return typeof raw[storageKey] === "boolean" ? raw[storageKey] : defaultExpanded;
    } catch { return defaultExpanded; }
  });
  useEffect(() => {
    try {
      const raw = JSON.parse(localStorage.getItem("abyssal_subgroups") ?? "{}");
      localStorage.setItem("abyssal_subgroups", JSON.stringify({ ...raw, [storageKey]: expanded }));
    } catch {}
  }, [storageKey, expanded]);
  // Allow a curated view (e.g. WelcomeOverlay presets) to force-expand this
  // subgroup even though it's already mounted (mount-time state won't re-read).
  useEffect(() => {
    const onExpand = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (Array.isArray(detail)) {
        // legacy payload: expand-only
        if (detail.includes(storageKey)) setExpanded(true);
        return;
      }
      if (detail && Array.isArray(detail.expand)) {
        const inList = detail.expand.includes(storageKey);
        if (detail.collapseOthers) setExpanded(inList);
        else if (inList) setExpanded(true);
      }
    };
    window.addEventListener("abyssal:expand-subgroups", onExpand);
    return () => window.removeEventListener("abyssal:expand-subgroups", onExpand);
  }, [storageKey]);
  return (
    <div className="mt-4">
      <button
        onClick={() => setExpanded(v => !v)}
        aria-expanded={expanded}
        aria-label={t("common:tooltips.toggleSubSection", { label })}
        className="flex items-center justify-between w-full text-left pt-2 pb-1 border-t border-white/[0.06] group"
      >
        <span className="text-white/70 text-[10px] font-mono uppercase tracking-[0.12em] group-hover:text-white/85 transition-colors">{label}</span>
        <span className="text-white/55 text-[10px] font-mono group-hover:text-white/70 transition-colors">{expanded ? "▴" : "▾"}</span>
      </button>
      {expanded && <div className="mt-0.5">{children}</div>}
    </div>
  );
}

export function GroupHeader({ label, expanded, onToggle, badge }: {
  label: string; expanded: boolean; onToggle: () => void; badge?: string;
}) {
  const { t } = useTranslation(["panels", "common"]);
  return (
    <button
      onClick={onToggle}
      aria-expanded={expanded}
      aria-label={t("common:tooltips.toggleSection", { label })}
      className="flex items-center justify-between w-full text-left py-1.5 group"
    >
      <span className="text-white/80 text-[10px] font-mono uppercase tracking-[0.15em] group-hover:text-white/90 transition-colors">
        {label}{badge ? <span className="ml-1 text-white/60 font-normal">{badge}</span> : null}
      </span>
      <span className="text-white/60 text-[10px] font-mono group-hover:text-white/70 transition-colors">
        {expanded ? "▴" : "▾"}
      </span>
    </button>
  );
}

export type LayerRowProps = {
  id?: LayerId; label: string; color: string;
  active: boolean; onToggle: () => void; onLocate?: () => void;
  locateDataAttr?: string;
} & (
  | { filterContent?: never; filterActive?: never; expanded?: never; onExpandToggle?: never }
  | { filterContent: ReactNode; filterActive?: boolean; expanded: boolean; onExpandToggle: () => void }
);

function LayerTooltipPopup({
  layerId,
  tooltip,
  rowRef,
  tipRef,
  onTipEnter,
  onTipLeave,
}: {
  layerId: string;
  tooltip: LayerTooltipMeta;
  rowRef: React.RefObject<HTMLDivElement | null>;
  tipRef: React.RefObject<HTMLDivElement>;
  onTipEnter: () => void;
  onTipLeave: () => void;
}) {
  const { t } = useTranslation(["panels", "common"]);
  const [style, setStyle] = useState<React.CSSProperties>({ opacity: 0 });
  const description = (t as (k: string, opts: Record<string, unknown>) => string)(
    `tooltip.descriptions.${layerId}`,
    { defaultValue: "" },
  );

  useEffect(() => {
    if (!rowRef.current) return;
    const row = rowRef.current.getBoundingClientRect();
    const tipW = 320; // w-80
    const tipH = tipRef.current?.offsetHeight ?? 160;
    // Place to the right of the panel; if it overflows, flip left
    let left = row.right + 8;
    if (left + tipW > window.innerWidth) left = row.left - tipW - 8;
    // Vertically center on the row, but clamp to viewport
    let top = row.top + row.height / 2 - tipH / 2;
    top = Math.max(8, Math.min(top, window.innerHeight - tipH - 8));
    setStyle({ position: "fixed", left, top, opacity: 1 });
  }, [rowRef]);

  return createPortal(
    <div
      ref={tipRef}
      // pointer-events-auto so users can move into the tooltip and click the source link.
      // Close logic uses a shared grace timer in LayerRow; entering the tooltip cancels it.
      className="z-tooltip w-80 bg-[rgba(10,14,20,0.97)] border border-white/[0.08] rounded p-3 animate-fade-in pointer-events-auto"
      style={style}
      onMouseEnter={onTipEnter}
      onMouseLeave={onTipLeave}
    >
      {description && <p className="text-white/85 text-sm leading-relaxed mb-2">{description}</p>}
      {layerId === "argo" && (
        <div className="mb-2 space-y-1">
          <p className="text-white/70 text-[11px] uppercase tracking-wider mb-1">{t("tooltip.argoReadingHeading")}</p>
          <p className="text-white/80 text-[13px] leading-relaxed">{t("tooltip.argoOxygenGuide")}</p>
          <p className="text-white/80 text-[13px] leading-relaxed">{t("tooltip.argoPhGuide")}</p>
        </div>
      )}
      {layerId === "monitoring-density" && (
        <div className="mb-2">
          <p className="text-white/70 text-[11px] uppercase tracking-wider mb-1">{t("tooltip.densityScaleLabel")}</p>
          {/* Swatches MUST stay in sync with getFillColor in Map3D.tsx and
              colorRampHex in LegendPanel.tsx — one scale, three render sites. */}
          <div className="space-y-0.5">
            {([["#f0f0d2", "0–4"], ["#e1c86e", "5–19"], ["#e68c32", "20–59"], ["#c82d23", "60–199"], ["#8c1414", "200+"]] as const).map(([hex, range]) => (
              <div key={range} className="flex items-center gap-2">
                <span className="w-3.5 h-3.5 rounded-sm shrink-0 border border-white/10" style={{ backgroundColor: hex }} />
                <span className="text-white/80 text-sm font-mono">{range}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {layerId === "vme-suitability" && (
        <div className="mb-2">
          <p className="text-white/70 text-[11px] uppercase tracking-wider mb-1">{t("tooltip.vmeScaleLabel")}</p>
          {/* Swatches MUST stay in sync with VME_RAMP in Map3D.tsx and
              colorRampHex in LegendPanel.tsx — one scale, three render sites. */}
          <div className="space-y-0.5">
            {([["#440154", "0.00"], ["#3b528b", "0.25"], ["#21918c", "0.50"], ["#5ec962", "0.75"], ["#fde725", "1.00"]] as const).map(([hex, v]) => (
              <div key={v} className="flex items-center gap-2">
                <span className="w-3.5 h-3.5 rounded-sm shrink-0 border border-white/10" style={{ backgroundColor: hex }} />
                <span className="text-white/80 text-sm font-mono">{v}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {layerId === "ocean-acidification" && (
        <div className="mb-2">
          <p className="text-white/70 text-[11px] uppercase tracking-wider mb-1">{t("tooltip.acidScaleLabel")}</p>
          {/* Diverging Ω ramp MUST stay in sync with div_acid in acidification.py and
              colorRampHex in LegendPanel.tsx — one scale, three render sites. */}
          <div className="space-y-0.5">
            {([["#b2182b", "< 1 — corrosive"], ["#f7f7f7", "1 — saturation"], ["#2166ac", "> 1 — supersaturated"]] as const).map(([hex, label]) => (
              <div key={label} className="flex items-center gap-2">
                <span className="w-3.5 h-3.5 rounded-sm shrink-0 border border-white/10" style={{ backgroundColor: hex }} />
                <span className="text-white/80 text-sm font-mono">{label}</span>
              </div>
            ))}
          </div>
          <p className="text-white/60 text-[11px] mt-1 leading-snug">
            Horizon view uses a separate shallow→deep ramp (shallow = corrosive water near surface).
          </p>
        </div>
      )}
      {layerId === "coral-acid-exposure" && (
        <div className="mb-2">
          <p className="text-white/70 text-[11px] uppercase tracking-wider mb-1">{t("tooltip.coralExposureScaleLabel")}</p>
          {/* Swatches MUST stay in sync with STATE_COLORS in
              backend/services/coral_acid_exposure.py and the /meta response
              consumed by Map3D.tsx getFillColor — one scale, two render sites. */}
          <div className="space-y-0.5">
            {([["#be1e5a", "Newly corrosive (since preindustrial)"], ["#8c5a96", "Corrosive (pre-industrial)"], ["#3c8caf", "Supersaturated"], ["#94a3b8", "No data"]] as const).map(([hex, label]) => (
              <div key={label} className="flex items-center gap-2">
                <span className="w-3.5 h-3.5 rounded-sm shrink-0 border border-white/10" style={{ backgroundColor: hex }} />
                <span className="text-white/80 text-sm font-mono">{label}</span>
              </div>
            ))}
          </div>
          <p className="text-white/60 text-[11px] mt-1 leading-snug">
            Exposure, not loss — see the click panel for the full disclosure.
          </p>
        </div>
      )}
      <p className="text-white/70 text-sm mb-2 leading-relaxed">
        <span className="text-white/70">{t("tooltip.sourceLabel")}</span>{" "}
        {tooltip.legendRef ? (
          <span>{tooltip.source}</span>
        ) : tooltip.sourceUrl ? (
          <a
            href={tooltip.sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-cyan-300/80 hover:text-cyan-200 underline decoration-dotted underline-offset-2"
          >
            {tooltip.source} <span aria-hidden="true">↗</span>
          </a>
        ) : (
          <span>{tooltip.source}</span>
        )}
      </p>
      {tooltip.legendRef && (
        <button
          type="button"
          onClick={() => useMapStore.getState().openLegendForLayer(tooltip.legendRef as string)}
          className="text-cyan-300/80 hover:text-cyan-200 text-sm underline decoration-dotted underline-offset-2 mb-2 inline-block"
        >
          {t("tooltip.methodologyLink", { defaultValue: "Methodology & sources →" })}
        </button>
      )}
      {tooltip.pairsWith.length > 0 && (
        <div>
          <p className="text-white/70 text-[11px] uppercase tracking-wider mb-1">{t("tooltip.pairsWellWith")}</p>
          <div className="flex flex-wrap gap-1">
            {tooltip.pairsWith.map(pid => (
              <span key={pid} className="text-[13px] text-white/80 bg-white/[0.06] rounded px-1.5 py-0.5">
                {(t as (k: string, opts: Record<string, unknown>) => string)(
                  `layers.${dashToCamel(pid)}.toggle`,
                  { defaultValue: LAYER_LABEL_MAP[pid] ?? pid },
                )}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>,
    document.body,
  );
}

export function LayerRow({ id, label, color, active, onToggle, onLocate, locateDataAttr, filterContent, filterActive, expanded, onExpandToggle }: LayerRowProps) {
  const enabledLayerIds = useMapStore((s) => s.enabledLayerIds);
  const { t } = useTranslation(["panels", "common"]);
  const [showTooltip, setShowTooltip] = useState(false);
  // Two timers: one for the open delay (hover the row 1 s before showing),
  // and one for the close grace period (give the user 250 ms to move the
  // cursor into the tooltip body to click the source link).
  const openTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const rowRef = useRef<HTMLDivElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const tooltip = id ? LAYER_TOOLTIPS_META[id] : undefined;

  const cancelClose = useCallback(() => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  }, []);

  const scheduleClose = useCallback(() => {
    cancelClose();
    closeTimerRef.current = setTimeout(() => setShowTooltip(false), 250);
  }, [cancelClose]);

  const onEnter = useCallback(() => {
    if (!tooltip) return;
    cancelClose();
    openTimerRef.current = setTimeout(() => setShowTooltip(true), 1000);
  }, [tooltip, cancelClose]);

  const onLeave = useCallback(() => {
    if (openTimerRef.current) {
      clearTimeout(openTimerRef.current);
      openTimerRef.current = null;
    }
    scheduleClose();
  }, [scheduleClose]);

  // Close tooltip on outside click (for touch devices). Tooltip is portalled
  // to document.body so a click inside it is NOT inside rowRef — exclude tipRef
  // explicitly, otherwise pointerdown closes the tooltip before the link's
  // click event can fire and the source link looks unclickable.
  useEffect(() => {
    if (!showTooltip) return;
    const close = (e: PointerEvent) => {
      const target = e.target as Node;
      const insideRow = rowRef.current?.contains(target);
      const insideTip = tipRef.current?.contains(target);
      if (!insideRow && !insideTip) {
        setShowTooltip(false);
      }
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [showTooltip]);

  // Hide rows for globally disabled/retired layers. Rows without an id (group
  // headers) always show. Placed after every hook call above so this early
  // return never skips a hook conditionally (rules-of-hooks).
  if (id && enabledLayerIds && !enabledLayerIds.has(id)) return null;

  return (
    <div
      ref={rowRef}
      className={`relative transition-opacity duration-150 ${active ? "opacity-100" : "opacity-65"}`}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
    >
      <div className="flex items-center gap-2 group py-0.5">
        <div className="shrink-0 w-5 h-5 flex items-center justify-center">
          {filterContent && (
            <button
              onClick={onExpandToggle}
              aria-label={expanded ? t("common:tooltips.collapseFilters") : t("common:tooltips.expandFilters")}
              aria-expanded={expanded}
              className="w-full h-full flex items-center justify-center text-white/70 hover:text-white/85 transition-colors relative -m-2 p-2"
            >
              <span className="text-[13px] leading-none font-mono">{expanded ? "−" : "+"}</span>
              {filterActive && !expanded && (
                <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-yellow-400/80" />
              )}
            </button>
          )}
        </div>
        <label className="flex items-center gap-2 flex-1 cursor-pointer min-w-0">
          <input
            type="checkbox"
            checked={active}
            onChange={onToggle}
            className="sr-only peer"
          />
          <div
            className="w-3 h-3 rounded-sm shrink-0 border transition-colors"
            style={{
              backgroundColor: active ? color : "transparent",
              borderColor: color,
            }}
          />
          <span className="text-[13px] text-white/85 truncate">{label}</span>
        </label>
        {tooltip && (
          <button
            onClick={() => setShowTooltip(v => !v)}
            aria-label={t("common:tooltips.infoAbout", { label })}
            aria-expanded={showTooltip}
            className="shrink-0 w-5 h-5 flex items-center justify-center text-white/70 hover:text-white/90 active:text-white/90 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
            </svg>
          </button>
        )}
        {onLocate && (
          <button
            onClick={onLocate}
            title={t("common:tooltips.zoomTo", { label })}
            aria-label={t("common:tooltips.zoomTo", { label })}
            className="opacity-60 group-hover:opacity-100 active:opacity-100 text-white/70 hover:text-white/95 active:text-white/95 transition-[opacity,color] shrink-0 p-1 sm:p-1 min-w-[44px] min-h-[44px] sm:min-w-0 sm:min-h-0 flex items-center justify-center"
            {...(locateDataAttr ? { "data-tutorial": locateDataAttr } : {})}
          >
            <LocateIcon />
          </button>
        )}
      </div>
      {filterContent && expanded && (
        <div className="pl-5 pb-1.5 pt-1 space-y-0.5 border-l border-white/[0.04] ml-2">
          {filterContent}
        </div>
      )}
      {showTooltip && tooltip && id && (
        <LayerTooltipPopup
          layerId={id}
          tooltip={tooltip}
          rowRef={rowRef}
          tipRef={tipRef}
          onTipEnter={cancelClose}
          onTipLeave={scheduleClose}
        />
      )}
    </div>
  );
}
