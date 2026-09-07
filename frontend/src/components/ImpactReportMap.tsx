// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useMemo } from "react";
import DeckGL from "@deck.gl/react";
import { ScatterplotLayer, PathLayer, GeoJsonLayer } from "@deck.gl/layers";
import { Map } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";

interface TrailProfile {
  lon: number;
  lat: number;
  alarms: string[];
  alarm_severities: Record<string, number>;
  nearest_claim_id: string | null;
}

interface Props {
  profiles: TrailProfile[];
  claimPolygons?: GeoJSON.FeatureCollection | null;
  plumeLines?: { from: [number, number]; to: [number, number] }[];
}

export function ImpactReportMap({ profiles, claimPolygons, plumeLines }: Props) {
  const bounds = useMemo(() => {
    if (profiles.length === 0) return null;
    let minLon = Infinity, maxLon = -Infinity, minLat = Infinity, maxLat = -Infinity;
    for (const p of profiles) {
      minLon = Math.min(minLon, p.lon);
      maxLon = Math.max(maxLon, p.lon);
      minLat = Math.min(minLat, p.lat);
      maxLat = Math.max(maxLat, p.lat);
    }
    const padLon = (maxLon - minLon) * 0.15 || 1;
    const padLat = (maxLat - minLat) * 0.15 || 1;
    return {
      longitude: (minLon + maxLon) / 2,
      latitude: (minLat + maxLat) / 2,
      zoom: Math.min(8, Math.max(2, -Math.log2(Math.max(maxLon - minLon + padLon, maxLat - minLat + padLat) / 360))),
    };
  }, [profiles]);

  const layers = useMemo(() => {
    if (profiles.length === 0) return [];
    const ls: any[] = [];

    // Claim polygons — filter out features with null/undefined geometry
    const validClaims = claimPolygons?.features?.filter(f => f.geometry?.type) ?? [];
    if (validClaims.length > 0) {
      ls.push(new GeoJsonLayer({
        id: "report-claims",
        data: { type: "FeatureCollection" as const, features: validClaims },
        filled: true,
        stroked: true,
        getFillColor: [0, 200, 255, 15],
        getLineColor: [0, 200, 255, 100],
        getLineWidth: 1,
        lineWidthMinPixels: 1,
        parameters: { depthTest: false },
        pickable: false,
      }));
    }

    // Trail path
    const pathCoords = profiles.map(p => [p.lon, p.lat] as [number, number]);
    ls.push(new PathLayer({
      id: "report-trail",
      data: [{ path: pathCoords }],
      getPath: (d: any) => d.path,
      getColor: [100, 255, 100, 150],
      getWidth: 2,
      widthMinPixels: 1.5,
      widthMaxPixels: 3,
      parameters: { depthTest: false },
      pickable: false,
    }));

    // Normal points
    const normal = profiles.filter(p => p.alarms.length === 0);
    if (normal.length > 0) {
      ls.push(new ScatterplotLayer({
        id: "report-points-normal",
        data: normal,
        getPosition: (d: any) => [d.lon, d.lat],
        getRadius: 8000,
        getFillColor: [100, 255, 100, 120],
        radiusMinPixels: 3,
        radiusMaxPixels: 6,
        parameters: { depthTest: false },
        pickable: false,
      }));
    }

    // Alarmed points
    const alarmed = profiles.filter(p => p.alarms.length > 0);
    if (alarmed.length > 0) {
      ls.push(new ScatterplotLayer({
        id: "report-points-alarmed",
        data: alarmed,
        getPosition: (d: any) => [d.lon, d.lat],
        getRadius: (d: any) => {
          const maxSev = Math.max(...Object.values(d.alarm_severities as Record<string, number>), 0.1);
          return 8000 + maxSev * 20000;
        },
        getFillColor: [239, 68, 68, 200],
        getLineColor: [255, 255, 255, 200],
        stroked: true,
        lineWidthMinPixels: 1,
        radiusMinPixels: 4,
        radiusMaxPixels: 12,
        parameters: { depthTest: false },
        pickable: false,
      }));
    }

    // Plume arrows
    if (plumeLines && plumeLines.length > 0) {
      ls.push(new PathLayer({
        id: "report-plumes",
        data: plumeLines.map(l => ({ path: [l.from, l.to] })),
        getPath: (d: any) => d.path,
        getColor: [214, 164, 64, 180],
        getWidth: 2,
        widthMinPixels: 1.5,
        capRounded: true,
        parameters: { depthTest: false },
        pickable: false,
      }));
    }

    return ls;
  }, [profiles, claimPolygons, plumeLines]);

  if (!bounds) return null;

  return (
    <div className="w-full h-64 rounded-xl overflow-hidden border border-white/10">
      <DeckGL
        initialViewState={{ ...bounds, pitch: 0, bearing: 0 }}
        controller={false}
        layers={layers}
        style={{ position: "relative", width: "100%", height: "100%" }}
      >
        <Map
          mapStyle="https://basemaps.cartocdn.com/gl/dark-matter-nolabels-gl-style/style.json"
          attributionControl={false}
        />
      </DeckGL>
    </div>
  );
}
