// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";
import {
  effectiveOceanColourMonth, type OceanColourMeta, type OceanColourPoint,
} from "../../../types/oceanColour";
import { API } from "../shared/tokens";
import { Badge, Section } from "../shared/primitives";

const VARIABLES = ["chl", "pp"] as const;
type Row = { key: (typeof VARIABLES)[number]; point: OceanColourPoint | null };

/** Fixed-point with enough digits for the magnitude: 0.0123, 1.23, 12.3, 123. */
export function formatOceanColourValue(v: number): string {
  const a = Math.abs(v);
  if (a >= 100) return v.toFixed(0);
  if (a >= 10) return v.toFixed(1);
  if (a >= 1) return v.toFixed(2);
  return v.toFixed(3);
}

/** 0.5 -> "50 %", 1 -> "100 %", 0.0278 -> "3 %"; a share of cells, so never fractional. */
export function formatValidFraction(f: number): string {
  return `${Math.round(f * 100)} %`;
}

/**
 * Point panel for `ocean-colour-satellite`. Shows both variables for the month the map
 * is displaying, read from the exact float grid (not the 8-bit texture), with the
 * product that supplied the month and the share of 4 km source cells behind the value.
 * ⛔ A missing value is never rendered as 0: `no_data` (no satellite observation) and
 * `not_covered` (outside the grid) each get their own sentence.
 */
export function OceanColourPanel({ props: p }: { props: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const lat = p._lat as number;
  const lon = p._lon as number;
  const chosenMonth = useMapStore((s) => s.oceanColourMonth);

  const [meta, setMeta] = useState<OceanColourMeta | null>(null);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    fetch(`${API}/api/v1/ocean-colour/meta`, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((m: OceanColourMeta) => setMeta(m))
      .catch(() => { if (!ctrl.signal.aborted) setFailed(true); });
    return () => ctrl.abort();
  }, []);

  const month = effectiveOceanColourMonth(meta, chosenMonth);

  useEffect(() => {
    if (!month) return;
    setRows(null);
    setFailed(false);
    const ctrl = new AbortController();
    Promise.all(VARIABLES.map(async (key): Promise<Row> => {
      const r = await fetch(
        `${API}/api/v1/ocean-colour/point?lat=${lat}&lon=${lon}&var=${key}&month=${month}`,
        { signal: ctrl.signal },
      );
      if (!r.ok) throw new Error(String(r.status));
      return { key, point: (await r.json()) as OceanColourPoint };
    }))
      .then((out) => setRows(out))
      .catch(() => { if (!ctrl.signal.aborted) setFailed(true); });
    return () => ctrl.abort();
  }, [lat, lon, month]);

  if (failed) return <p className="text-white/60 text-xs">{t("oceanColour.panel.failed")}</p>;
  if (!rows || !meta) return <p className="text-white/60 text-xs animate-pulse">Loading…</p>;

  const first = rows[0].point;
  const status = first?.status ?? "no_data";
  const productKey = first?.product_key ?? meta.month_products[month ?? ""] ?? null;
  const product = productKey ? meta.products[productKey] : null;
  const label = (key: string) => t(`oceanColour.variable.${key}`, {
    defaultValue: meta.variables.find((v) => v.key === key)?.label ?? key,
  });

  return (
    <>
      <p className="text-[11px] text-sky-300 leading-snug mb-2">{t("oceanColour.satelliteNote")}</p>
      <Badge label={t("oceanColour.panel.badge")} color="text-sky-300 border-sky-500/40" />
      <p className="text-sm text-white/80 mb-1">
        {t("oceanColour.panel.where", { lat: lat.toFixed(2), lon: lon.toFixed(2), month })}
      </p>
      {productKey && (
        <p className="text-[11px] text-white/65 mb-3">
          {t("oceanColour.panel.product", { product: t(`oceanColour.product.${productKey}`) })}
        </p>
      )}

      {status === "not_covered" ? (
        <p className="text-white/65 text-xs">{t("oceanColour.panel.notCovered")}</p>
      ) : status === "no_data" ? (
        <p className="text-white/65 text-xs">{t("oceanColour.panel.noData")}</p>
      ) : (
        <Section title={t("oceanColour.panel.section")}>
          <div className="overflow-x-auto rounded border border-white/10">
            <table className="w-full text-[11px] font-mono">
              <tbody>
                {rows.map(({ key, point }) => {
                  const raw = point ? point[point.value_field] : null;
                  const value = typeof raw === "number" ? raw : null;
                  return (
                    <tr key={key} className="odd:bg-white/[0.025]">
                      <td className="px-2 py-0.5 text-white/85">{label(key)}</td>
                      <td className="px-2 py-0.5 text-right text-sky-300">
                        {value != null ? formatOceanColourValue(value) : "—"}
                      </td>
                      <td className="px-2 py-0.5 text-right text-white/70">{point?.unit ?? ""}</td>
                      <td className="px-2 py-0.5 text-right text-white/55">
                        {value != null && point?.valid_fraction != null ? formatValidFraction(point.valid_fraction) : ""}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-white/60 mt-1">{t("oceanColour.panel.footnote")}</p>
          <p className="text-[11px] text-white/60 mt-1">{t("oceanColour.ppHint")}</p>
        </Section>
      )}

      <p className="text-[11px] text-white/65 mt-2">
        {meta.attribution}{" "}
        {product && (
          <a
            href={product.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sky-400 hover:underline"
          >
            {product.title} <span aria-hidden="true">↗</span>
          </a>
        )}
      </p>
    </>
  );
}
