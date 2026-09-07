// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { API } from "../shared/tokens";
import { Row, Section, Badge, PanelHeader, WarningBanner, SourceFooter } from "../shared/primitives";

// ── Monitoring density cell panel ────────────────────────────────────────────

const DENSITY_SOURCE_LABELS: Record<string, string> = {
  "chess":      "ChEssBase chemosynthetic sites",
  "argo":       "Argo float profiles",
  "oceansites": "OceanSITES moorings",
  "onc":        "ONC instruments",
  "obis":       "OBIS hotspot grid",
  "wod":        "World Ocean Database (WOD)",
  "pangaea":    "PANGAEA research cruises",
  "bco-dmo":    "BCO-DMO ocean datasets",
  "noaa":       "NOAA ocean surveys",
  "seamap":     "OBIS-SEAMAP megafauna",
  "cchdo":      "CCHDO / GO-SHIP cruises",
  "sio_bic":    "SIO Benthic Invertebrate Collection",
  "deepdata_isa": "DeepData ISA (contractor reports)",
  "mbari_vars": "MBARI VARS (deep-sea ROV)",
  "noaa_corals": "NOAA Deep-Sea Coral & Sponge",
};

function densityCoverageLabel(cnt: number): { label: string; color: string } {
  if (cnt < 5)  return { label: "Monitoring gap",      color: "text-red-400" };
  if (cnt < 20) return { label: "Sparse coverage",     color: "text-orange-400" };
  if (cnt < 60) return { label: "Moderate coverage",   color: "text-amber-400" };
  return               { label: "Well-observed",       color: "text-emerald-400" };
}

type DensitySample = { id: string; title: string; year: number | null };
type DensitySource = { src: string; count: number; samples: DensitySample[] };
type ChessSpeciesItem = { id: string; species: string; phylum: string; depth_m: number | null; institution: string };

function sampleLink(src: string, id: string): string | null {
  if (!id) return null;
  if (src === "pangaea") return `https://doi.pangaea.de/10.1594/${id}`;
  if (src === "cchdo")   return `https://cchdo.ucsd.edu/search?q=${encodeURIComponent(id)}`;
  if (src === "onc")     return `https://data.oceannetworks.ca/DeviceListing?DeviceId=${encodeURIComponent(id)}`;
  if (src === "sio_bic") return `https://sioapps.ucsd.edu/collections/bi/catalog/${encodeURIComponent(id)}/`;
  if (src === "deepdata_isa") return `https://obis.org/occurrence/${encodeURIComponent(id)}`;
  if (src === "mbari_vars") return `https://obis.org/occurrence/${encodeURIComponent(id)}`;
  if (src === "noaa_corals") return `https://www.ncei.noaa.gov/maps/deep-sea-corals/mapSites.htm?CatalogNumber=${encodeURIComponent(id)}`;
  if (src === "ncei" && id.startsWith("http")) return id;
  if (id.startsWith("10.")) return `https://doi.org/${id}`;
  return null;
}

function sourceBrowseLink(src: string, lonMin: number, latMin: number): string | null {
  const lonMax = lonMin + 2;
  const latMax = latMin + 2;
  if (src === "obis") {
    return `https://mapper.obis.org/?bbox=${lonMin},${latMin},${lonMax},${latMax}`;
  }
  if (src === "seamap") {
    return `https://seamap.env.duke.edu/search?bbox=${lonMin},${latMin},${lonMax},${latMax}`;
  }
  if (src === "pangaea") {
    return `https://www.pangaea.de/?q=&env=${lonMin}W${lonMax}E${latMax}N${latMin}S`;
  }
  if (src === "ncei" || src === "noaa") {
    return `https://www.ncei.noaa.gov/access/search/data-search/global-marine?bbox=${lonMin},${latMax},${lonMax},${latMin}`;
  }
  if (src === "argo") {
    return `https://argovis.colorado.edu/plots/plot?shapes=%5B%5B%5B${lonMin},${latMin}%5D,%5B${lonMin},${latMax}%5D,%5B${lonMax},${latMax}%5D,%5B${lonMax},${latMin}%5D,%5B${lonMin},${latMin}%5D%5D%5D`;
  }
  if (src === "deepdata_isa") {
    // OBIS moved node pages from /area?nodeid= to /node/ — same UUID, new route.
    return `https://obis.org/node/9d2d95be-32eb-4d81-8911-32cb8bc641c8`;
  }
  if (src === "mbari_vars") {
    return `https://www.mbari.org/data/`;
  }
  if (src === "noaa_corals") {
    return `https://deepseacoraldata.noaa.gov/`;
  }
  return null;
}

const NO_SAMPLES_SRCS = new Set(["obis", "seamap"]);

export function MonitoringDensityPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  const cellLon = Number(p.centroid_lon ?? 0);
  const cellLat = Number(p.centroid_lat ?? 0);
  const pointCount = Number(p.point_count ?? 0);
  const sourceCount = Number(p.source_count ?? 0);

  const [sources, setSources] = useState<DensitySource[] | null>(null);
  const [distinctSpecies, setDistinctSpecies] = useState<number | null>(null);
  const [loadingBreakdown, setLoadingBreakdown] = useState(true);
  const [expandedSrc, setExpandedSrc] = useState<string | null>(null);
  const [chessSpecies, setChessSpecies] = useState<ChessSpeciesItem[] | null>(null);
  const [chessLoading, setChessLoading] = useState(false);
  const [allSamples, setAllSamples] = useState<Record<string, DensitySample[]>>({});
  const [fetchingSrc, setFetchingSrc] = useState<string | null>(null);

  useEffect(() => {
    setLoadingBreakdown(true);
    setSources(null);
    setDistinctSpecies(null);
    setExpandedSrc(null);
    setChessSpecies(null);
    setAllSamples({});
    setFetchingSrc(null);
    fetch(`${API}/api/v2/map/monitoring-density/cell?lon=${cellLon}&lat=${cellLat}`)
      .then(r => r.json())
      .then(d => { setSources(d.sources ?? []); setDistinctSpecies(typeof d.distinct_species === "number" ? d.distinct_species : null); })
      .catch(() => setSources([]))
      .finally(() => setLoadingBreakdown(false));
  }, [cellLon, cellLat]);

  useEffect(() => {
    if (expandedSrc !== "chess" || chessSpecies !== null) return;
    setChessLoading(true);
    fetch(`${API}/api/v2/map/monitoring-density/chess-species?lon=${cellLon}&lat=${cellLat}`)
      .then(r => r.json())
      .then((data: ChessSpeciesItem[]) => { setChessSpecies(Array.isArray(data) ? data : []); })
      .catch(() => setChessSpecies([]))
      .finally(() => setChessLoading(false));
  }, [expandedSrc, cellLon, cellLat, chessSpecies]);

  useEffect(() => {
    if (!expandedSrc || expandedSrc === "chess") return;
    if (expandedSrc in allSamples) return;
    const srcData = sources?.find(s => s.src === expandedSrc);
    if (!srcData || srcData.count <= srcData.samples.length) return;
    const src = expandedSrc;
    setFetchingSrc(src);
    fetch(`${API}/api/v2/map/monitoring-density/source-all?lon=${cellLon}&lat=${cellLat}&src=${encodeURIComponent(src)}`)
      .then(r => r.json())
      .then((data: DensitySample[]) => {
        setAllSamples(prev => ({ ...prev, [src]: Array.isArray(data) ? data : [] }));
      })
      .catch(() => setAllSamples(prev => ({ ...prev, [src]: [] })))
      .finally(() => setFetchingSrc(null));
  }, [expandedSrc, sources, allSamples, cellLon, cellLat]);

  const { label: coverageLabel, color: coverageColor } = densityCoverageLabel(pointCount);
  const maxCount = sources && sources.length > 0 ? sources[0].count : 1;

  return (
    <>
      <Badge label={t("monitoringDensity.panelBadge")} color="text-orange-300 border-orange-500/40" />
      <PanelHeader>
        <span className={coverageColor}>{coverageLabel}</span>
      </PanelHeader>

      <Section title={t("monitoringDensity.cellSectionTitle")}>
        <Row label={t("monitoringDensity.centroidLabel")} value={`${cellLon.toFixed(2)}° E, ${cellLat.toFixed(2)}° N`} />
        <Row label={t("monitoringDensity.cellSizeLabel")} value={t("monitoringDensity.cellSizeValue")} />
        <Row label={t("monitoringDensity.totalRecordsLabel")} value={pointCount.toLocaleString()} />
        <Row label={t("monitoringDensity.sourcesContributingLabel")} value={`${sourceCount} / 15`} />
        {typeof distinctSpecies === "number" && distinctSpecies > 0 && (
          <Row
            label={t("monitoringDensity.distinctSpeciesLabel")}
            value={distinctSpecies.toLocaleString()}
          />
        )}
        {/* 15 sources: chess, argo, oceansites, onc, obis, wod, pangaea, bco-dmo, noaa, seamap, sio_bic, deepdata_isa, mbari_vars, noaa_corals, cchdo */}
      </Section>

      <Section title={t("monitoringDensity.sourceBreakdownSectionTitle")}>
        {loadingBreakdown ? (
          <p className="text-white/60 text-xs py-1">Loading…</p>
        ) : sources && sources.length > 0 ? (
          <div className="space-y-2 py-0.5">
            {sources.map(({ src, count, samples }) => {
              const pct = Math.round((count / maxCount) * 100);
              const hasSamples = !NO_SAMPLES_SRCS.has(src) && samples.length > 0;
              const isExpanded = expandedSrc === src;
              const browseUrl = sourceBrowseLink(src, cellLon, cellLat);
              return (
                <div key={src}>
                  <button
                    className="w-full text-left group"
                    onClick={() => hasSamples ? setExpandedSrc(isExpanded ? null : src) : undefined}
                    disabled={!hasSamples}
                  >
                    <div className="flex justify-between text-xs mb-0.5">
                      <span className="text-white/80 truncate group-hover:text-white/90 transition-colors">
                        {DENSITY_SOURCE_LABELS[src] ?? src}
                        {hasSamples && (
                          <span className="ml-1 text-white/60">{isExpanded ? "▼" : "▶"}</span>
                        )}
                      </span>
                      <span className="flex items-center gap-2 ml-2 shrink-0">
                        {browseUrl && (
                          <a
                            href={browseUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="text-[10px] text-orange-300/70 hover:text-orange-200 underline underline-offset-2 decoration-orange-400/30"
                            title={t("monitoringDensity.portalLinkTitle")}
                          >
                            portal ↗
                          </a>
                        )}
                        <span className="text-white/65 font-mono">{count.toLocaleString()}</span>
                      </span>
                    </div>
                    <div className="h-1 rounded-full bg-white/10 overflow-hidden">
                      <div className="h-full rounded-full bg-orange-400/60" style={{ width: `${pct}%` }} />
                    </div>
                  </button>
                  {isExpanded && (
                    <ul className="mt-1.5 space-y-1 pl-2 border-l border-white/10">
                      {src === "chess" ? (
                        <>
                          {chessLoading && (
                            <li className="text-[11px] text-white/60">Loading species…</li>
                          )}
                          {!chessLoading && (chessSpecies ?? []).map((item, i) => (
                            <li key={i} className="text-[11px] leading-tight">
                              <span className="text-white/85 italic">{item.species || item.id}</span>
                              {item.phylum && (
                                <span className="text-white/60 ml-1.5">· {item.phylum}</span>
                              )}
                              {item.depth_m != null && (
                                <span className="text-white/55 ml-1.5">· {Math.round(item.depth_m)} m</span>
                              )}
                            </li>
                          ))}
                          {!chessLoading && chessSpecies && chessSpecies.length < count && (
                            <li className="text-[11px] text-white/55 pt-0.5">
                              Showing {chessSpecies.length} of {count.toLocaleString()}
                            </li>
                          )}
                        </>
                      ) : (
                        <>
                          {fetchingSrc === src && (
                            <li className="text-[11px] text-white/60">Loading…</li>
                          )}
                          {(allSamples[src] ?? samples).map((s, i) => {
                            const url = sampleLink(src, s.id);
                            return (
                              <li key={i} className="text-[11px] leading-tight">
                                {url ? (
                                  <a
                                    href={url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-orange-300/80 hover:text-orange-200 underline underline-offset-2 decoration-orange-400/30 line-clamp-2"
                                  >
                                    {s.title || s.id}
                                  </a>
                                ) : (
                                  <span className="text-white/70 line-clamp-2">{s.title || s.id}</span>
                                )}
                                {s.year != null && (
                                  <span className="text-white/55 ml-1">{s.year}</span>
                                )}
                              </li>
                            );
                          })}
                          {!allSamples[src] && count > samples.length && !fetchingSrc && (
                            <li className="text-[11px] text-white/55 pt-0.5">
                              Showing {samples.length} of {count.toLocaleString()}
                            </li>
                          )}
                        </>
                      )}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-white/60 text-xs py-1">{t("monitoringDensity.noBreakdownText")}</p>
        )}
      </Section>

      <WarningBanner color="orange">
        {t("monitoringDensity.warningBanner")}
      </WarningBanner>

      <SourceFooter>
        Sources: OBIS, ChEssBase, Argo, OceanSITES, ONC, WOD, PANGAEA, BCO-DMO, NOAA, OBIS-SEAMAP, CCHDO, SIO-BIC, DeepData (ISA), MBARI VARS, NOAA Deep-Sea Coral &amp; Sponge
      </SourceFooter>
    </>
  );
}
