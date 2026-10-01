// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";
import { effectiveBgcMonth, type BgcModelMeta, type BgcModelPoint } from "../../../types/bgcModel";
import { API } from "../shared/tokens";
import { Badge, Section, WarningBanner } from "../shared/primitives";

const VARIABLES = ["no3", "chl", "nppv", "nstar"] as const;
type Row = { key: (typeof VARIABLES)[number]; point: BgcModelPoint | null };

/** Fixed-point with enough digits for the magnitude: 0.0123, 1.23, 12.3, 123. */
export function formatNutrientValue(v: number): string {
  const a = Math.abs(v);
  if (a >= 100) return v.toFixed(0);
  if (a >= 10) return v.toFixed(1);
  if (a >= 1) return v.toFixed(2);
  return v.toFixed(3);
}

/**
 * Point panel for `ocean-nutrients-model`. Shows all four variables for the month
 * the map is displaying, read from the exact float grid (not the 8-bit texture).
 * ⛔ A null is never rendered as 0: `no_data` (land or ice) and `not_covered`
 * (outside the 0.25° model grid, e.g. south of 80°S) each get their own sentence.
 */
export function NutrientsModelPanel({ props: p }: { props: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const lat = p._lat as number;
  const lon = p._lon as number;
  const chosenMonth = useMapStore((s) => s.nutrientsMonth);

  const [meta, setMeta] = useState<BgcModelMeta | null>(null);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    fetch(`${API}/api/v1/bgc-model/meta`, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((m: BgcModelMeta) => setMeta(m))
      .catch(() => { if (!ctrl.signal.aborted) setFailed(true); });
    return () => ctrl.abort();
  }, []);

  const month = effectiveBgcMonth(meta, chosenMonth);

  useEffect(() => {
    if (!month) return;
    setRows(null);
    setFailed(false);
    const ctrl = new AbortController();
    Promise.all(VARIABLES.map(async (key): Promise<Row> => {
      const r = await fetch(
        `${API}/api/v1/bgc-model/point?lat=${lat}&lon=${lon}&var=${key}&month=${month}`,
        { signal: ctrl.signal },
      );
      if (!r.ok) throw new Error(String(r.status));
      return { key, point: (await r.json()) as BgcModelPoint };
    }))
      .then((out) => setRows(out))
      .catch(() => { if (!ctrl.signal.aborted) setFailed(true); });
    return () => ctrl.abort();
  }, [lat, lon, month]);

  if (failed) return <p className="text-white/60 text-xs">{t("nutrients.panel.failed")}</p>;
  if (!rows || !meta) return <p className="text-white/60 text-xs animate-pulse">Loading…</p>;

  const status = rows[0].point?.status ?? "no_data";
  const label = (key: string) => t(`nutrients.variable.${key}`, {
    defaultValue: meta.variables.find((v) => v.key === key)?.label ?? key,
  });

  return (
    <>
      <WarningBanner color="orange">{t("nutrients.modelWarning")}</WarningBanner>
      <Badge label={t("nutrients.panel.badge")} color="text-emerald-300 border-emerald-500/40" />
      <p className="text-sm text-white/80 mb-3">
        {t("nutrients.panel.where", { lat: lat.toFixed(2), lon: lon.toFixed(2), month })}
      </p>

      {status === "not_covered" ? (
        <p className="text-white/65 text-xs">{t("nutrients.panel.notCovered")}</p>
      ) : status === "no_data" ? (
        <p className="text-white/65 text-xs">{t("nutrients.panel.noData")}</p>
      ) : (
        <Section title={t("nutrients.panel.section")}>
          <div className="overflow-x-auto rounded border border-white/10">
            <table className="w-full text-[11px] font-mono">
              <tbody>
                {rows.map(({ key, point }) => {
                  const raw = point ? point[point.value_field] : null;
                  const value = typeof raw === "number" ? raw : null;
                  return (
                    <tr key={key} className="odd:bg-white/[0.025]">
                      <td className="px-2 py-0.5 text-white/85">{label(key)}</td>
                      <td className="px-2 py-0.5 text-right text-emerald-300">
                        {value != null ? formatNutrientValue(value) : "—"}
                      </td>
                      <td className="px-2 py-0.5 text-right text-white/70">{point?.unit ?? ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-white/60 mt-1">{t("nutrients.panel.footnote")}</p>
          <p className="text-[11px] text-white/60 mt-1">{t("nutrients.nppvHint")}</p>
          <p className="text-[11px] text-white/60 mt-1">{t("woaPoint.nstarHint")}</p>
        </Section>
      )}

      <p className="text-[11px] text-white/65 mt-2">
        {meta.attribution}{" "}
        <a
          href={meta.product.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-emerald-400 hover:underline"
        >
          {meta.product.title} <span aria-hidden="true">↗</span>
        </a>
      </p>
    </>
  );
}
