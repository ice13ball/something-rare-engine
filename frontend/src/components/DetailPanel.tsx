// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useMapStore } from "../store/mapStore";
import type { SelectedFeature } from "../store/mapStore";

import { T } from "./panels/shared/tokens";
import { SeabedSubstratePanel } from "./panels/seabed/SeabedSubstratePanel";
import { CascadeStationPanel } from "./panels/seabed/CascadeStationPanel";
import { CascadeFieldPanel } from "./panels/seabed/CascadeFieldPanel";
import { NoiseRiskPanel } from "./panels/density/NoiseRiskPanel";
import { MonitoringDensityPanel } from "./panels/density/MonitoringDensityPanel";
import { WodOxygenPanel } from "./panels/fields/WodOxygenPanel";
import { WoaPointPanel } from "./panels/fields/WoaPointPanel";
import { CarbonPointPanel } from "./panels/fields/CarbonPointPanel";
import { AcidificationPointPanel } from "./panels/fields/AcidificationPointPanel";
import { ChiPanel } from "./panels/fields/ChiPanel";
import { UnifiedCarbonPanel } from "./panels/fields/UnifiedCarbonPanel";
import { VmeSuitabilityPanel } from "./panels/fields/VmeSuitabilityPanel";
import { CoralExposurePanel } from "./panels/fields/CoralExposurePanel";
import { Co2PointPanel } from "./panels/fields/Co2PointPanel";
import { OxygenPointPanel } from "./panels/fields/OxygenPointPanel";
import { DeepDataStationPanel } from "./panels/density/DeepDataStationPanel";
import { MiningFootprintPanel } from "./panels/land/MiningFootprintPanel";
import { TailingsPanel } from "./panels/land/TailingsPanel";
import { FirePanel } from "./panels/land/FirePanel";
import { AirQualityPanel } from "./panels/land/AirQualityPanel";
import { LandslidePanel } from "./panels/land/LandslidePanel";
import { DamPanel } from "./panels/land/DamPanel";
import { SurfaceWaterPanel } from "./panels/land/SurfaceWaterPanel";
import { WaterRiskPanel } from "./panels/land/WaterRiskPanel";
import { OffshoreActivityPanel } from "./panels/land/OffshoreActivityPanel";
import { VesselEventPanel } from "./panels/land/VesselEventPanel";
import { VesselTrackPointPanel } from "./panels/land/VesselTrackPointPanel";
import { AisVesselPanel } from "./panels/land/AisVesselPanel";
import { MiningPanel } from "./panels/ocean/MiningPanel";
import { VentPanel } from "./panels/ocean/VentPanel";
import { ArgoPanel } from "./panels/ocean/ArgoPanel";
import { TrailDotPanel } from "./panels/ocean/TrailDotPanel";
import { SeamountPanel } from "./panels/ocean/SeamountPanel";
import { BiodiversityGridPanel } from "./panels/ocean/BiodiversityGridPanel";
import { BiodiversityPanel } from "./panels/ocean/BiodiversityPanel";
import { RelinquishedPanel } from "./panels/ocean/RelinquishedPanel";
import { ReservedAreaPanel } from "./panels/ocean/ReservedAreaPanel";
import { ApeiPanel } from "./panels/ocean/ApeiPanel";
import { EezPanel } from "./panels/ocean/EezPanel";
import { ProtectedSitePanel } from "./panels/ocean/ProtectedSitePanel";
import { PlumeOriginPanel } from "./panels/ocean/PlumeOriginPanel";
import { OceansitesPanel } from "./panels/ocean/OceansitesPanel";
import { OncPanel } from "./panels/ocean/OncPanel";
import { HydrophoneStationPanel } from "./panels/ocean/HydrophoneStationPanel";
import { ChessPanel } from "./panels/ocean/ChessPanel";
import { CablePanel } from "./panels/ocean/CablePanel";
import { OncCablePanel } from "./panels/ocean/OncCablePanel";
import { OoiCablePanel } from "./panels/ocean/OoiCablePanel";
import { NoaaCablePanel } from "./panels/ocean/NoaaCablePanel";
import { NzCablePanel } from "./panels/ocean/NzCablePanel";
import { AuCablePanel } from "./panels/ocean/AuCablePanel";
import { OncInstrumentPanel } from "./panels/ocean/OncInstrumentPanel";
import { PortPanel } from "./panels/ocean/PortPanel";
import { TectonicPanel } from "./panels/ocean/TectonicPanel";
import { ArcticRiverPanel } from "./panels/arctic/ArcticRiverPanel";
import { SiosPanel } from "./panels/arctic/SiosPanel";
import { PermafrostThawPanel } from "./panels/arctic/PermafrostThawPanel";
import { SeafleaPanel } from "./panels/arctic/SeafleaPanel";
import { MementoPanel } from "./panels/arctic/MementoPanel";
import { MementoHexPanel } from "./panels/arctic/MementoHexPanel";
import { GeotracesStationPanel } from "./panels/arctic/GeotracesStationPanel";
import { GeotracesHexPanel } from "./panels/arctic/GeotracesHexPanel";
import { MosaicPanel } from "./panels/arctic/MosaicPanel";
import { MosaicHexPanel } from "./panels/arctic/MosaicHexPanel";
import { ArcticCatchmentPanel } from "./panels/arctic/ArcticCatchmentPanel";


function PanelContent({ feature }: { feature: SelectedFeature }) {
  const { layer, id, properties } = feature;
  if (layer === "mining-contracts-mvt")       return <MiningPanel id={String(id)} />;
  if (layer === "hydrothermal-vents-active" ||
      layer === "hydrothermal-vents-inactive") return <VentPanel id={Number(id)} />;
  if (layer === "argo-floats-3d")             return <ArgoPanel properties={properties} />;
  if (layer === "argo-trail-dot")             return <TrailDotPanel properties={properties} />;
  if (layer === "seamounts")                  return <SeamountPanel properties={properties} />;
  if (layer === "biodiversity-hotspots" ||
      layer === "biodiversity-hotspots-grid-coarse" ||
      layer === "biodiversity-hotspots-grid-fine") {
    if (properties.total_count != null)         return <BiodiversityGridPanel properties={properties} />;
    return <BiodiversityPanel properties={properties} />;
  }
  if (layer === "relinquished-areas")         return <RelinquishedPanel properties={properties} />;
  if (layer === "reserved-areas")             return <ReservedAreaPanel properties={properties} />;
  if (layer === "apeis")                      return <ApeiPanel properties={properties} />;
  if (layer === "eez")                        return <EezPanel properties={properties} />;
  if (layer === "protected-marine-sites")     return <ProtectedSitePanel properties={properties} />;
  if (layer === "plume-origin")               return <PlumeOriginPanel properties={properties} />;
  if (layer === "monitoring-density")         return <MonitoringDensityPanel properties={properties} />;
  if (layer === "deepdata-stations")          return <DeepDataStationPanel properties={properties} />;
  if (layer === "noise-risk")                 return <NoiseRiskPanel properties={properties} />;
  if (layer === "oceansites")                 return <OceansitesPanel properties={properties} />;
  if (layer === "onc")                        return <OncPanel properties={properties} />;
  if (layer === "hydrophone-stations")        return <HydrophoneStationPanel properties={properties} />;
  if (layer === "chess")                      return <ChessPanel properties={properties} />;
  if (layer === "submarine-cables")           return <CablePanel properties={properties} />;
  if (layer === "onc-cables")                 return <OncCablePanel properties={properties} />;
  if (layer === "ooi-cables")                 return <OoiCablePanel properties={properties} />;
  if (layer === "noaa-cables")                return <NoaaCablePanel properties={properties} />;
  if (layer === "nz-cables")                  return <NzCablePanel properties={properties} />;
  if (layer === "au-cables")                  return <AuCablePanel properties={properties} />;
  if (layer === "onc-instruments")            return <OncInstrumentPanel properties={properties} />;
  if (layer === "ports")                      return <PortPanel properties={properties} />;
  if (layer === "tectonic-plates-fill" ||
      layer === "tectonic-plates-boundaries") return <TectonicPanel properties={properties} />;
  // Land layers
  if (layer === "mining-footprints" || layer === "mining-footprints-mvt") return <MiningFootprintPanel properties={properties} />;
  if (layer === "tailings")                   return <TailingsPanel properties={properties} />;
  if (layer === "fires")                      return <FirePanel properties={properties} />;
  if (layer === "air-quality")                return <AirQualityPanel properties={properties} />;
  if (layer === "landslides")                 return <LandslidePanel properties={properties} />;
  if (layer === "dams")                       return <DamPanel properties={properties} />;
  if (layer === "water-risk" || layer === "water-risk-mvt") return <WaterRiskPanel properties={properties} />;
  if (layer === "surface-water")              return <SurfaceWaterPanel />;
  if (layer === "offshore-activities" || layer === "offshore-activities-mvt" || layer === "offshore-zones-mvt") return <OffshoreActivityPanel properties={properties} />;
  if (layer === "vessel-events" || properties?.__type === "vessel_event") return <VesselEventPanel feature={feature} />;
  if (layer === "ais-live" || properties?.__type === "ais_vessel") return <AisVesselPanel properties={properties} />;
  if (layer === "vessel-track-point") return <VesselTrackPointPanel properties={properties} />;
  if (layer === "sios-svalbard")              return <SiosPanel properties={properties} />;
  if (layer === "methane-seeps")              return <SeafleaPanel properties={properties} />;
  if (layer === "permafrost-thaw")            return <PermafrostThawPanel properties={properties} />;
  if (layer === "arctic-rivers")              return <ArcticRiverPanel properties={properties} />;
  if (layer === "wod-oxygen")                 return <WodOxygenPanel id={id} />;
  if (layer === "memento")        return <MementoPanel id={id} />;
  if (layer === "memento-hexes")  return <MementoHexPanel properties={properties} />;
  if (layer === "geotraces")      return <GeotracesStationPanel id={id} />;
  if (layer === "geotraces-hexes") return <GeotracesHexPanel properties={properties} />;
  if (layer === "mosaic-sediment") return <MosaicPanel coreId={String(properties.core_id ?? id)} />;
  if (layer === "mosaic-hexes")    return <MosaicHexPanel properties={properties} />;
  if (layer === "arctic-catchments") return <ArcticCatchmentPanel gid={properties.gid as number} />;
  if (layer === "woa-climatology")            return <WoaPointPanel props={properties} />;
  if (layer === "oxygen-deox")               return <OxygenPointPanel props={properties} />;
  if (layer === "ocean-carbon")              return <CarbonPointPanel props={properties} />;
  if (layer === "marine-carbon")             return <UnifiedCarbonPanel props={properties} />;
  if (layer === "vme-suitability")           return <VmeSuitabilityPanel props={properties} />;
  if (layer === "ocean-acidification")       return <AcidificationPointPanel props={properties} />;
  if (layer === "cumulative-human-impact")   return <ChiPanel props={properties} />;
  if (layer === "coral-acid-exposure")       return <CoralExposurePanel props={properties} />;
  if (layer === "ocean-co2-surface")         return <Co2PointPanel props={properties} />;
  if (layer === "seabed-substrate")          return <SeabedSubstratePanel feature={feature} />;
  if (layer === "arctic-sediment-carbon-stations") return <CascadeStationPanel feature={feature} />;
  if (layer === "arctic-sediment-carbon")          return <CascadeFieldPanel feature={feature} />;
  return <p className="text-white/60 text-xs">No details available.</p>;
}


// ── Panel chrome title ──────────────────────────────────────────────────────
// The panel header bar should show a friendly category (e.g. "Hydrothermal
// Vent"), not the raw deck.gl sublayer id ("hydrothermal-vents-active"). Map the
// known layer families; fall back to the id minus its render-variant suffix.
const LAYER_TITLE: Record<string, string> = {
  "hydrothermal-vents": "Hydrothermal Vent",
  "mining-contracts": "Mining Concession",
  "offshore-activities": "Offshore Activity",
  "offshore-zones": "Offshore Zone",
  "biodiversity-hotspots": "Biodiversity Record",
  "argo-floats": "Argo Float",
  "deepdata-stations": "DeepData Station",
  "hydrophone-stations": "Hydrophone Station",
  "oceansites": "OceanSITES Mooring",
  "onc": "ONC Observatory",
  "seamounts": "Seamount",
  "seabed-substrate": "Seabed Substrate",
  "tectonic-plates": "Tectonic Plate",
  "submarine-cables": "Submarine Cable",
  "noaa-cables": "Submarine Cable",
  "onc-cables": "Submarine Cable",
  "ooi-cables": "Submarine Cable",
  "nz-cables": "Submarine Cable",
  "au-cables": "Submarine Cable",
  "protected-marine-sites": "Protected Marine Site",
  "water-risk": "Water Risk Basin",
  "monitoring-density": "Monitoring Density",
  "fires": "Fire Detection",
  "tailings": "Tailings Facility",
  "landslides": "Landslide",
  "dams": "Dam",
  "ports": "Port",
  "eez": "Maritime Zone",
  "relinquished-areas": "Relinquished Area",
  "reserved-areas": "Reserved Area",
  "air-quality": "Air Quality Station",
  "mining-footprints": "Mining Footprint",
  "forest-loss": "Forest Loss",
  "noise-risk": "Noise Risk",
  "carbon-flux": "Carbon Flux",
  "soil-carbon": "Soil Carbon",
  "surface-water": "Surface Water",
  "wod-oxygen":    "WOD O₂ Profile",
  "sios-svalbard":  "SIOS Dataset",
  "arctic-rivers": "Arctic River Station",
  "methane-seeps": "Methane Seep",
  "permafrost-thaw": "Permafrost Thaw Feature",
  "memento":         "MEMENTO Cast",
  "memento-hexes":   "MEMENTO Density",
  "geotraces":           "GEOTRACES Station",
  "geotraces-hexes":    "GEOTRACES Density",
  "mosaic-sediment":    "MOSAIC Sediment Core",
  "mosaic-hexes":       "MOSAIC Density",
  "arctic-catchments":  "Arctic Catchment",
  "ocean-carbon":      "Ocean Carbon (GLODAP)",
  "ocean-carbon-hexes": "Ocean Carbon Density",
  "ocean-acidification": "Ocean Acidification (GLODAP Ω)",
  "ocean-acidification-hexes": "Ocean Acidification Density",
  "coral-acid-exposure": "Coral Acidification Exposure",
  "coral-acid-exposure-hexes": "Coral Acidification Exposure",
  "cumulative-human-impact": "Cumulative Human Impact",
  "cumulative-human-impact-hexes": "Cumulative Human Impact",
  "marine-carbon-hexes": "Marine Carbon",
  "ocean-co2-surface":       "Surface Ocean CO₂ (SOCAT)",
  "ocean-co2-surface-hexes": "Surface CO₂ Density",
  "arctic-sediment-carbon-stations": "Sediment Station",
  "arctic-sediment-carbon": "Arctic Sediment Carbon",
};
const _VARIANT_SUFFIX = /-(active|inactive|glow|mvt|fill|line|labels|boundaries|3d|instruments)$/;
function prettyLayerLabel(layerId: string): string {
  if (LAYER_TITLE[layerId]) return LAYER_TITLE[layerId];
  const base = layerId.replace(_VARIANT_SUFFIX, "");
  return LAYER_TITLE[base] ?? base.replace(/-/g, " ");
}

// ── Draggable panel wrapper ────────────────────────────────────────────────────

function DraggablePanel({
  feature,
  onClose,
}: {
  feature: SelectedFeature;
  onClose: () => void;
}) {
  const { t } = useTranslation(["panels", "common"]);
  const panelRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const dragState = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null);

  // Use feature.slot (stable, assigned at creation) so panels don't jump when
  // other panels are added or removed from the selectedFeatures array.
  useEffect(() => {
    const pw = 320; // panel width (w-80 = 320px)
    const cascade = 24;
    const x = window.innerWidth - pw - 16 - feature.slot * cascade;
    setPos({ x: Math.max(0, x), y: 60 + feature.slot * cascade });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    if (!pos) return;
    e.preventDefault();
    dragState.current = { startX: e.clientX, startY: e.clientY, origX: pos.x, origY: pos.y };
    const onMouseMove = (ev: MouseEvent) => {
      if (!dragState.current) return;
      const dx = ev.clientX - dragState.current.startX;
      const dy = ev.clientY - dragState.current.startY;
      setPos({ x: dragState.current.origX + dx, y: dragState.current.origY + dy });
    };
    const onMouseUp = () => {
      dragState.current = null;
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  }, [pos]);

  // Touch support for mobile dragging
  const onTouchStart = useCallback((e: React.TouchEvent) => {
    if (!pos || !e.touches[0]) return;
    const touch = e.touches[0];
    dragState.current = { startX: touch.clientX, startY: touch.clientY, origX: pos.x, origY: pos.y };
    const onTouchMove = (ev: TouchEvent) => {
      if (!dragState.current || !ev.touches[0]) return;
      const dx = ev.touches[0].clientX - dragState.current.startX;
      const dy = ev.touches[0].clientY - dragState.current.startY;
      setPos({ x: dragState.current.origX + dx, y: dragState.current.origY + dy });
    };
    const onTouchEnd = () => {
      dragState.current = null;
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", onTouchEnd);
    };
    window.addEventListener("touchmove", onTouchMove, { passive: false });
    window.addEventListener("touchend", onTouchEnd);
  }, [pos]);

  if (!pos) return null;

  return (
    <div
      ref={panelRef}
      className="fixed z-overlay w-80 max-h-[80vh] overflow-y-auto custom-scrollbar rounded-xl border border-white/10 bg-surface-primary shadow-2xl"
      style={{ left: pos.x, top: pos.y }}
    >
      <div
        className="flex items-center justify-between px-4 py-3 border-b border-white/5 cursor-grab active:cursor-grabbing select-none"
        onMouseDown={onMouseDown}
        onTouchStart={onTouchStart}
      >
        <span className={`${T.sectionH} truncate pr-2 mb-0`}>
          {prettyLayerLabel(feature.layer)}
        </span>
        <button
          onClick={onClose}
          className="text-white/60 hover:text-white text-lg leading-none transition-colors shrink-0"
          aria-label={t("common:actions.close")}
        >
          ×
        </button>
      </div>
      <div className="px-4 py-4">
        <PanelContent feature={feature} />
      </div>
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

export function DetailPanel() {
  const { selectedFeatures, removeSelectedFeature } = useMapStore();
  const { t } = useTranslation(["panels", "common"]);

  if (selectedFeatures.length === 0) return null;

  return (
    <div aria-live="polite" aria-label={t("common:tooltips.featureDetails")}>
      {selectedFeatures.map((feature) => (
        <DraggablePanel
          key={`${feature.layer}-${feature.id}`}
          feature={feature}
          onClose={() => removeSelectedFeature(feature.id, feature.layer)}
        />
      ))}
    </div>
  );
}
