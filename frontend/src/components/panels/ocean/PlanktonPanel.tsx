// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Click panel for one plankton place (`/api/v1/plankton/site/{site_key}`, backend/domains/plankton.py).
 * ⛔ Sends the ACTIVE map filters, so the panel describes exactly the dot that was clicked.
 * ⛔ Coordinates come from the response (the place), never from the click point: a panel opened
 *    from a share link has no click point.
 * ⛔ Missing and broken never share a state: 404 = the place is not in the current import, anything else =
 *    unavailable, with a retry. Never a blank panel.
 * ⛔ Dataset titles/citations are rendered as React text (never as HTML).
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";
import { PLANKTON_GROUP_HEX, planktonFilterQuery, type PlanktonGroup } from "../../../utils/plankton";
import { API } from "../shared/tokens";
import { PanelHeader, Row, Section } from "../shared/primitives";

export interface PlanktonSite {
  site_key: string;
  lon: number;
  lat: number;
  total: number;
  groups: { taxon_group: string; n: number }[];
  top_species: { scientific_name: string; taxon_group: string; n: number }[];
  years: { min: number | null; max: number | null; undated: number };
  depth: { min_m: number | null; max_m: number | null; no_depth: number };
  edna: { n: number; share: number };
  licences: { licence: string; n: number }[];
  datasets: { dataset_id: string; title: string | null; citation: string | null; url: string | null;
              licence: string; n: number; obis_url: string }[];
  datasets_total: number;
}

export function planktonSiteUrl(siteKey: string, query: string): string {
  return `${API}/api/v1/plankton/site/${encodeURIComponent(siteKey)}${query ? `?${query}` : ""}`;
}

const fmt = (n: number) => n.toLocaleString("en-US");
/** Only ever link to OBIS over https; anything else is shown as plain text. */
const safeObis = (u: string) => /^https:\/\/obis\.org\//.test(u);

export function PlanktonPanel({ siteKey }: { siteKey: string }) {
  const { t } = useTranslation("panels");
  const groups = useMapStore((s) => s.planktonGroupFilters);
  const decades = useMapStore((s) => s.planktonDecadeFilters);
  const bands = useMapStore((s) => s.planktonDepthFilters);
  const showEdna = useMapStore((s) => s.planktonShowEdna);
  const query = planktonFilterQuery({ groups, decades, bands, showEdna });
  const [data, setData] = useState<PlanktonSite | null>(null);
  const [state, setState] = useState<"loading" | "missing" | "error" | "ok">("loading");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    setState("loading");
    setData(null);
    fetch(planktonSiteUrl(siteKey, query), { signal: ctrl.signal })
      .then((r) => {
        if (r.status === 404) { setState("missing"); return null; }
        if (!r.ok) throw new Error(String(r.status));       // 503 + Retry-After lands here too
        return r.json();
      })
      .then((j) => { if (j) { setData(j as PlanktonSite); setState("ok"); } })
      .catch((e) => { if (e?.name !== "AbortError") setState("error"); });
    return () => ctrl.abort();
  }, [siteKey, query, attempt]);

  if (state === "loading") return <p className="text-white/60 text-xs animate-pulse">{t("planktonSite.loading")}</p>;
  if (state === "missing") return <p className="text-white/70 text-sm" role="status">{t("planktonSite.missing")}</p>;
  if (state === "error" || !data) {
    return (
      <div role="alert">
        <p className="text-amber-300/90 text-sm mb-2">{t("planktonSite.error")}</p>
        <button type="button" onClick={() => setAttempt((n) => n + 1)}
          className="text-xs text-cyan-300 border border-cyan-500/40 rounded px-2 py-1 hover:bg-cyan-500/10">
          {t("planktonSite.retry")}
        </button>
      </div>
    );
  }

  const years = data.years.min === null ? t("planktonSite.noYears")
    : data.years.min === data.years.max ? String(data.years.min) : `${data.years.min}–${data.years.max}`;
  const depth = data.depth.min_m === null ? t("planktonSite.noDepths")
    : `${Math.round(data.depth.min_m)}–${Math.round(data.depth.max_m ?? data.depth.min_m)} m`;
  const hasNc = data.licences.some((l) => l.licence === "cc-by-nc");

  return (
    <div data-testid="plankton-panel">
      <PanelHeader>{t("planktonSite.title")}</PanelHeader>
      <p className="text-white/70 text-xs font-mono mb-2">{`${Number(data.lat).toFixed(4)}, ${Number(data.lon).toFixed(4)}`}</p>
      {data.total === 0 ? (
        <p className="text-white/70 text-sm" role="status">{t("planktonSite.noMatch")}</p>
      ) : (
        <>
          <Row label={t("planktonSite.observations")} value={fmt(data.total)} />
          <Row label={t("planktonSite.years")}
            value={`${years}${data.years.undated ? ` · ${t("planktonSite.undated", { n: data.years.undated })}` : ""}`} />
          <Row label={t("planktonSite.depth")}
            value={`${depth}${data.depth.no_depth ? ` · ${t("planktonSite.noDepth", { n: data.depth.no_depth })}` : ""}`} />
          {data.edna.n > 0 && (
            <Row label={t("planktonSite.edna")}
              value={t("planktonSite.ednaShare", {
                n: fmt(data.edna.n), pct: data.edna.share < 0.01 ? "<1" : Math.round(data.edna.share * 100),
              })} />
          )}
          <Section title={t("planktonSite.groups")}>
            <ul className="text-xs text-white/85">
              {data.groups.map((g) => (
                <li key={g.taxon_group} className="flex items-center gap-2">
                  <span className="inline-block w-2 h-2 rounded-full"
                    style={{ backgroundColor: PLANKTON_GROUP_HEX[g.taxon_group as PlanktonGroup] ?? "#94a3b8" }} />
                  {t(`filters.plankton.group.${g.taxon_group}`, { defaultValue: g.taxon_group })} — {fmt(g.n)}
                </li>
              ))}
            </ul>
          </Section>
          <Section title={t("planktonSite.topSpecies")}>
            <ol className="text-xs text-white/85 list-decimal ml-4">
              {data.top_species.map((sp) => (
                <li key={`${sp.taxon_group}:${sp.scientific_name}`}><i>{sp.scientific_name}</i> — {fmt(sp.n)}</li>
              ))}
            </ol>
          </Section>
          <Section title={t("planktonSite.licences")}>
            <p className="text-xs text-white/85">
              {data.licences.map((l) => `${l.licence.toUpperCase()} ${fmt(l.n)}`).join(" · ")}
            </p>
            {hasNc && <p className="text-[11px] text-amber-300/90 mt-1">{t("planktonSite.ncNote")}</p>}
          </Section>
          <Section title={t("planktonSite.datasets", { n: data.datasets_total })}>
            <ul className="text-xs text-white/85 space-y-1.5">
              {data.datasets.map((d) => (
                <li key={d.dataset_id}>
                  {safeObis(d.obis_url) ? (
                    <a href={d.obis_url} target="_blank" rel="noopener noreferrer" className="text-cyan-300 hover:underline">
                      {d.title ?? d.dataset_id}
                    </a>
                  ) : (<span>{d.title ?? d.dataset_id}</span>)}{" "}
                  <span className="text-white/60">({d.licence.toUpperCase()}, {fmt(d.n)})</span>
                  {d.citation && <p className="text-white/60 text-[11px]">{d.citation}</p>}
                </li>
              ))}
            </ul>
          </Section>
        </>
      )}
    </div>
  );
}
