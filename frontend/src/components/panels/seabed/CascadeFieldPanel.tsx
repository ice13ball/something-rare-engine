// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { PanelHeader, Row, WarningBanner } from "../shared/primitives";
import { SampleYearRange } from "../shared/SampleYearRange";

export function CascadeFieldPanel({ feature }: { feature: any }) {
  const p = feature.properties || {};
  const { t } = useTranslation(["panels", "legend"]);
  const VLABEL: Record<string, string> = { oc: "Organic carbon", tn: "Total nitrogen", d13c: "δ¹³C", d14c: "Δ¹⁴C" };
  // Absent on an older backend deployed to /v1/cascade/point before this field
  // existed, and null whenever no station falls inside the 50 km radius —
  // both must render fine, so this stays a plain optional read, never a crash.
  const ctx = p.sampling_context as
    | { n_samples: number; year_min: number | null; year_max: number | null;
        year_median: number | null; n_undated: number; caveat_key: string }
    | null
    | undefined;
  return (
    <div>
      <PanelHeader>{VLABEL[p.variable] ?? "Sediment carbon"}</PanelHeader>
      <div className="text-2xl font-semibold mt-1"><span className="text-amber-200">{p.value != null ? Number(p.value).toFixed(2) : "—"}</span> <span className="text-sm font-normal text-white/60">{p.unit}</span></div>
      <WarningBanner color="orange">{t("panels:arcticSedimentCarbon.fieldCaveat", "Interpolated 5 km surface — modelled, not a raw measurement.")}</WarningBanner>
      {ctx ? (
        <>
          <Row
            label={t("legend:sampleDate.range")}
            value={
              <SampleYearRange
                yearMin={ctx.year_min}
                yearMax={ctx.year_max}
                count={ctx.n_samples}
                nUndated={ctx.n_undated}
              />
            }
          />
          <p className="text-white/60 text-xs mt-1">{t(`panels:${ctx.caveat_key}` as any)}</p>
        </>
      ) : null}
      <div className="text-xs text-white/40 mt-2">CASCADE v2 · Martens et al. 2021 · CC-BY 4.0</div>
    </div>
  );
}
