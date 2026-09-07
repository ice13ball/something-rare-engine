// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";

export interface SampleDateProps {
  precision: "day" | "month" | "year" | "campaign" | "none" | null;
  year?: number | null;
  month?: number | null;
  day?: number | null;
  campaignStart?: string | null; // ISO "YYYY-MM-DD"
  campaignEnd?: string | null;
  campaignName?: string | null;
  comment?: string | null;
}

const pad = (n: number) => String(n).padStart(2, "0");

/**
 * The only place that turns a source date into text.
 *
 * The rule it enforces (docs/methods/data-passthrough.md, "Sampling time"):
 * render exactly the granularity the source gave. A year never becomes
 * 1 January; a calendar day is never shortened to a year. A missing date is
 * stated, never rendered as blank — blank reads as "not loaded yet", which
 * is a different claim.
 *
 * The numeric format (`2008-08-12`) is identical in every locale; only the
 * words around it ("campaign", "no date at source") are translated.
 */
export function SampleDate(p: SampleDateProps) {
  const { t } = useTranslation("legend");

  // date_precision is NULL on every row ingested before that column existed
  // (25,608 rows as of the 2026-09 backfill; re-sync had not run yet). NULL
  // there does not mean the source gave no date — sampling_year is real and
  // sits right next to it in the same response. Falling through to "none"
  // would claim "no date at source" about a row that has a year, which is
  // the precision-erasure half of the data-passthrough rule. Treat a null/
  // undefined precision with a known year as "year" rather than "none".
  const precision = p.precision == null && p.year != null ? "year" : p.precision;

  let text: string;
  switch (precision) {
    case "day":
      text =
        p.year != null && p.month != null && p.day != null
          ? `${p.year}-${pad(p.month)}-${pad(p.day)}`
          : "—";
      break;
    case "month":
      text = p.year != null && p.month != null ? `${p.year}-${pad(p.month)}` : "—";
      break;
    case "year":
      text = p.year != null ? String(p.year) : "—";
      break;
    case "campaign":
      text = `${t("sampleDate.campaign")} ${p.campaignStart ?? "?"} → ${p.campaignEnd ?? "?"}`;
      break;
    default:
      text = t("sampleDate.noDateAtSource");
  }

  return (
    <span>
      <span className="font-mono">{text}</span>
      {p.campaignName && precision === "campaign" && (
        <span className="text-white/60 ml-1">({p.campaignName})</span>
      )}
      {p.comment && <span className="block text-white/60 text-[11px] mt-0.5">{p.comment}</span>}
    </span>
  );
}
