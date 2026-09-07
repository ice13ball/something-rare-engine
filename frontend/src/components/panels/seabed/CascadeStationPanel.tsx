// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { PanelHeader, Section } from "../shared/primitives";

export function CascadeStationPanel({ feature }: { feature: any }) {
  const p = feature.properties || {};
  const { t } = useTranslation(["panels"]);
  const rows: [string, any, string][] = [
    ["OC", p.oc_pct, "%"], ["TN", p.tn_pct, "%"], ["OC:N", p.oc_tn, ""],
    ["δ¹³C", p.d13c, "‰"], ["Δ¹⁴C", p.d14c, "‰"],
    ["HMW alkanes", p.hmw_alkanes, "µg/gOC"], ["HMW acids", p.hmw_acids, "µg/gOC"],
    ["Lignin", p.lignin, "mg/gOC"],
  ];
  return (
    <div>
      <PanelHeader>{`Station ${p.station ?? p.station_id ?? ""}`}</PanelHeader>
      <Section title={t("panels:sections.measurements", "Measurements")}>
        <table className="w-full text-sm">
          <tbody>
            {rows.filter(([, v]) => v != null).map(([k, v, u]) => (
              <tr key={k}><td className="text-white/60">{k}</td>
                <td className="text-right text-white/90 tabular-nums">{typeof v === "number" ? v.toFixed(2) : v}{u ? ` ${u}` : ""}</td></tr>
            ))}
          </tbody>
        </table>
      </Section>
      <div className="text-xs text-white/50 mt-2">
        {p.expedition ? `${p.expedition}, ` : ""}{p.year ?? ""}{p.water_depth_m != null ? ` — ${p.water_depth_m} mbsl` : ""}
      </div>
      <div className="text-xs text-white/40 mt-2">
        CASCADE v2 · Martens et al. 2021, ESSD 13:2561 · CC-BY 4.0 ·{" "}
        <a className="text-cyan-400" href="https://doi.org/10.17043/cascade-2" target="_blank" rel="noreferrer">DOI</a>
      </div>
    </div>
  );
}
