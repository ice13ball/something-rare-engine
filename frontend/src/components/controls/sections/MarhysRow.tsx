// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";
import type { LayerId } from "../../../types/layers";
import { LayerRow, FilterResetLink } from "../rows";

interface Props {
  expandedFilter: LayerId | null;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

interface MarhysMeta {
  total_samples: number;
  coord_status: Record<string, number>;
  sample_types: Array<{ code: string; total: number; mapped: number }>;
}

/** Colours mirror `map3d/colors.ts::marhysTypeColor` — warm is vent fluid, cool is reference seawater. */
const TYPE_SWATCH: Record<string, string> = {
  HF: "#fb923c",
  EM: "#ef4444",
  SW: "#38bdf8",
};


/**
 * ⛔ Spelled out rather than built with `layers.marhys.types.${code}`. The
 * project type-checks every translation key against `en/panels.json`, and a
 * template literal over `string` defeats that check — the one guard standing
 * between a typo and a raw key rendered to a user.
 */
const TYPE_LABEL_KEY = {
  HF: "layers.marhys.types.HF",
  EM: "layers.marhys.types.EM",
  SW: "layers.marhys.types.SW",
  STD: "layers.marhys.types.STD",
} as const;

export function MarhysRow({ expandedFilter, toggleExpand, toggle, flyToLayer }: Props) {
  const {
    activeLayers,
    marhysView, setMarhysView,
    marhysTypeFilters, toggleMarhysTypeFilter,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);
  const [meta, setMeta] = useState<MarhysMeta | null>(null);

  // ⛔ THE FILTER'S OPTIONS COME FROM THE SERVER'S OWN COUNTS, not a constant.
  // MARHYS ships ten `STD` (calibration standard) samples and not one of them
  // carries a coordinate, so a hard-coded option for it would be a control that
  // can never match a marker however it is clicked. Anything with `mapped === 0`
  // is dropped here for the same reason, whatever the source adds later.
  useEffect(() => {
    if (!activeLayers.has("marhys") || meta) return;
    let cancelled = false;
    fetch("/api/v1/map/marhys/meta")
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (!cancelled && d) setMeta(d as MarhysMeta); })
      .catch(() => { /* the row still works without counts; it just shows fewer of them */ });
    return () => { cancelled = true; };
  }, [activeLayers, meta]);

  const mappableTypes = (meta?.sample_types ?? []).filter(s => s.mapped > 0);
  const unplaceable =
    (meta?.coord_status?.missing ?? 0) + (meta?.coord_status?.out_of_range ?? 0);

  return (
    <LayerRow
      id="marhys"
      label={t("layers.marhys.toggle")}
      color="#fb923c"
      active={activeLayers.has("marhys")}
      onToggle={() => toggle("marhys")}
      onLocate={() => flyToLayer?.("marhys")}
      filterActive={marhysTypeFilters.size > 0}
      expanded={expandedFilter === "marhys"}
      onExpandToggle={() => toggleExpand("marhys")}
      filterContent={
        <div className="flex flex-col gap-3">
          {/* View — display state, NOT a filter. Both views draw the same rows. */}
          <div className="flex flex-col gap-1">
            <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">
              {t("layers.marhys.view")}
            </span>
            <div className="flex gap-1">
              {(["points", "density"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setMarhysView(v)}
                  className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-colors ${
                    marhysView === v
                      ? "bg-orange-500 border-orange-500 text-white"
                      : "border-white/20 text-white/65 bg-white/5"
                  }`}
                >
                  {t(`layers.marhys.views.${v}`)}
                </button>
              ))}
            </div>
          </div>

          {/* Sample type — a real filter (resets with the others). */}
          {mappableTypes.length > 0 && (
            <div className="flex flex-col gap-1">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">
                  {t("layers.marhys.sampleType")}
                </span>
                {marhysTypeFilters.size > 0 && (
                  <FilterResetLink
                    show
                    onReset={() => marhysTypeFilters.forEach(toggleMarhysTypeFilter)}
                  />
                )}
              </div>
              <div className="flex flex-wrap gap-1">
                {mappableTypes.map(({ code, mapped }) => {
                  const active = marhysTypeFilters.size === 0 || marhysTypeFilters.has(code);
                  return (
                    <button
                      key={code}
                      onClick={() => toggleMarhysTypeFilter(code)}
                      title={TYPE_LABEL_KEY[code as keyof typeof TYPE_LABEL_KEY]
                        ? t(TYPE_LABEL_KEY[code as keyof typeof TYPE_LABEL_KEY])
                        : code}
                      className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-colors flex items-center gap-1 ${
                        active
                          ? "bg-white/15 border-white/40 text-white"
                          : "border-white/20 text-white/50 bg-white/5"
                      }`}
                    >
                      <span
                        className="inline-block w-2 h-2 rounded-full"
                        style={{ background: TYPE_SWATCH[code] ?? "#94a3b8" }}
                      />
                      {code}
                      <span className="text-white/45">{mapped.toLocaleString()}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* ⛔ Not decoration. The source carries 6,788 samples and only 5,905
              can be placed; a layer that shows the smaller number while the
              documentation quotes the larger one invites the reader to think
              883 samples were lost. Saying it here costs one line. */}
          {meta && unplaceable > 0 && (
            <p className="text-[10px] leading-snug text-white/45 font-mono">
              {t("layers.marhys.unplaceable", {
                count: unplaceable,
                // Both numbers get the locale's own grouping. Without this the
                // line read "883 of 6788" beside chips showing "4,317".
                total: meta.total_samples.toLocaleString(),
              })}
            </p>
          )}
        </div>
      }
    />
  );
}
