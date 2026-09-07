// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMapStore } from "../store/mapStore";

const API = import.meta.env.VITE_API_BASE_URL ?? "";

/**
 * Mission-control status strip — bottom-left instrument cluster.
 *
 * Honest readouts only: a system dot (green = nominal, amber = a layer
 * fetch failed), ticking UTC clock, age of the most recent backend sync,
 * active layer count, and the zoom level (absorbed from the old lone
 * z-indicator). Desktop-only except the zoom readout, which stays on
 * mobile to preserve the previous behaviour.
 */
export function StatusStrip({ zoom, degraded }: { zoom: number; degraded: boolean }) {
  const { t } = useTranslation("common");
  const activeCount = useMapStore(s => s.activeLayers.size);

  // Ticking UTC clock (1 s)
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  // Latest backend sync timestamp — fetched once, refreshed every 5 min
  const [latestSync, setLatestSync] = useState<Date | null>(null);
  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch(`${API}/api/v1/sync/status`)
        .then(r => (r.ok ? r.json() : {}))
        .then((dates: Record<string, string>) => {
          if (cancelled) return;
          const ts = Object.values(dates)
            .map(d => new Date(d).getTime())
            .filter(n => Number.isFinite(n));
          if (ts.length) setLatestSync(new Date(Math.max(...ts)));
        })
        .catch(() => {});
    };
    load();
    const id = setInterval(load, 5 * 60 * 1000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const utc = now.toISOString().slice(11, 19);

  let syncAge: string | null = null;
  if (latestSync) {
    const mins = Math.max(0, Math.round((now.getTime() - latestSync.getTime()) / 60000));
    if (mins < 60) syncAge = t("statusStrip.minutesShort", { n: mins });
    else if (mins < 48 * 60) syncAge = t("statusStrip.hoursShort", { n: Math.round(mins / 60) });
    else syncAge = t("statusStrip.daysShort", { n: Math.round(mins / 1440) });
  }

  return (
    <div
      aria-label={t("statusStrip.ariaLabel")}
      className="absolute bottom-2 left-4 z-10 flex items-center gap-3 text-[10px] font-mono tracking-wider text-white/65 pointer-events-none select-none"
    >
      {/* System dot + state — desktop only */}
      <span className="hidden sm:flex items-center gap-1.5">
        <span
          className={`w-1.5 h-1.5 rounded-full status-pulse ${degraded ? "bg-amber-400" : "bg-emerald-400/90"}`}
        />
        <span className={degraded ? "text-amber-300/80" : "text-white/70"}>
          {degraded ? t("statusStrip.degraded") : t("statusStrip.tracking")}
        </span>
      </span>

      {/* UTC clock — desktop only */}
      <span className="hidden sm:inline text-white/75 tabular-nums">{utc} UTC</span>

      {/* Last backend sync age — desktop only, omitted until known */}
      {syncAge && (
        <span className="hidden sm:inline">
          {t("statusStrip.sync")} <span className="text-white/75">{syncAge}</span>
        </span>
      )}

      {/* Active layer count — desktop only */}
      <span className="hidden sm:inline">
        {t("statusStrip.layers")} <span className="text-white/75 tabular-nums">{activeCount}</span>
      </span>

      {/* Zoom — all viewports (previous standalone indicator) */}
      <span className="tabular-nums">z{zoom.toFixed(1)}</span>
    </div>
  );
}
