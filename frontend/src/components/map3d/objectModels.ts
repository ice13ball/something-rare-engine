// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { CompositeLayer } from "@deck.gl/core";
import type { Layer, LayerContext, LayerProps, UpdateParameters, WebMercatorViewport } from "@deck.gl/core";
import { ColumnLayer, ScatterplotLayer } from "@deck.gl/layers";
import type { Feature, Point } from "geojson";
import { isConfirmedVentStatus } from "../../utils/ventStatus";
import type { ModelAssets } from "./modelAssets";
import { overviewScale, overviewWeight } from "./modelOverview";
import { ModelPlumeLayer } from "./modelPlume";

export type ModelKind = "seamount" | "active" | "inactive";
type PointFeature = Feature<Point>;
type ModelProps = { column: ColumnLayer; kind: ModelKind; data: PointFeature[] };
type Particle = { feature: PointFeature; phase: number };
function modelScale(feature: PointFeature, kind: ModelKind): [number, number, number] {
  const height = kind === "seamount" ? Math.max(Number(feature.properties?.height_m) || 300, 300)
    : kind === "active" ? 1800 : 800;
  return kind === "seamount" ? [height, height, height] : [height * 0.2, height * 0.2, height];
}
function hash(feature: PointFeature): number {
  const key = String(feature.id ?? feature.properties?.peak_id ?? feature.properties?.vent_id
    ?? feature.properties?.id ?? feature.geometry.coordinates.join(","));
  let value = 2166136261;
  for (let i = 0; i < key.length; i++) value = Math.imul(value ^ key.charCodeAt(i), 16777619);
  return value >>> 0;
}
const longitudeCell = (lon: number) => ((Math.floor(lon) + 180) % 360 + 360) % 360;
type ModelState = {
  assets?: ModelAssets; failed: boolean; groups: PointFeature[][];
  buckets: Map<string, PointFeature[]>; maxHeight: number; region: string;
  particles: Particle[]; particleKey: string;
  motion: MediaQueryList; onEnvironmentChange: () => void;
};

/** Static spatial buckets and padded group caching keep camera moves off full data. */
class ObjectModelsLayer extends CompositeLayer<ModelProps> {
  static layerName = "ObjectModelsLayer";
  declare state: ModelState;
  initializeState() {
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onEnvironmentChange = () => this.getCurrentLayer()?.setState({});
    this.state = { failed: false, groups: [], buckets: new Map(), maxHeight: 0, region: "",
      particles: [], particleKey: "", motion, onEnvironmentChange };
    motion.addEventListener("change", onEnvironmentChange);
    document.addEventListener("visibilitychange", onEnvironmentChange);
    void import("./modelAssets").then(module => module.loadModelAssets(this.props.kind)).then(assets => {
      this.getCurrentLayer()?.setState({ assets });
    }).catch(this.fail);
  }
  private fail = (error?: unknown) => {
    console.warn("[3d-models] falling back to columns:", error);
    this.getCurrentLayer()?.setState({ failed: true });
    return true;
  };
  shouldUpdateState({ changeFlags }: UpdateParameters<this>) {
    return !!(changeFlags.propsOrDataChanged || changeFlags.viewportChanged || changeFlags.stateChanged);
  }
  updateState({ changeFlags }: UpdateParameters<this>) {
    const { kind, column } = this.props;
    const viewport = this.context.viewport as WebMercatorViewport;
    const radius = column.props.radius;
    const weight = overviewWeight(viewport.zoom);
    if (changeFlags.dataChanged) {
      const buckets = new Map<string, PointFeature[]>();
      let maxHeight = 0;
      this.props.data.forEach((feature, index) => {
        const row = this.getSubLayerRow({ ...feature }, feature, index);
        const [lon, lat] = feature.geometry.coordinates;
        const key = `${longitudeCell(lon)}:${Math.floor(lat)}`;
        if (!buckets.has(key)) buckets.set(key, []);
        buckets.get(key)!.push(row);
        maxHeight = Math.max(maxHeight, modelScale(feature, kind)[2]);
      });
      this.setState({ buckets, maxHeight, region: "" });
    }
    // Include elevated summits outside the ground view; snap a padded box to
    // degree cells so normal panning reuses the same instance buffers.
    const [west, south, east, north] = viewport.getBounds();
    const height = this.state.maxHeight + radius * weight * (kind === "seamount" ? 2 : 10);
    const pad = 0.25 + height * (2 + Math.tan(Math.min(80, viewport.pitch) * Math.PI / 180)) / 111320;
    const lonPad = pad / Math.max(0.1, Math.cos(viewport.latitude * Math.PI / 180));
    const x0 = Math.floor(west - lonPad), x1 = Math.min(x0 + 359, Math.ceil(east + lonPad));
    const y0 = Math.max(-89, Math.floor(south - pad)), y1 = Math.min(89, Math.ceil(north + pad));
    const region = `${x0}:${x1}:${y0}:${y1}`;
    if (region !== this.state.region) {
      const groups: PointFeature[][] = Array.from({ length: kind === "seamount" ? 4 : 1 }, () => []);
      for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) {
        for (const row of this.state.buckets.get(`${longitudeCell(x)}:${y}`) || []) {
          groups[kind === "seamount" ? hash(row) % 4 : 0].push(row);
        }
      }
      this.setState({ groups, region });
    }
    if (kind === "active") {
      const scale = overviewScale([360, 360, 1800], radius, weight);
      const emitters = (this.state.groups[0] || []).filter(feature => {
        const [x, y, z] = viewport.project([...feature.geometry.coordinates.slice(0, 2), scale[2]]);
        return z >= -1 && z <= 1 && x >= 0 && x <= viewport.width && y >= 0 && y <= viewport.height;
      });
      const key = emitters.map(hash).join(",");
      if (key !== this.state.particleKey) {
        const particles = emitters.flatMap(feature => {
          const count = isConfirmedVentStatus(feature.properties?.status) ? 18 : 8;
          return Array.from({ length: count }, (_, slot) => ({ feature, phase: slot / count + hash(feature) % 97 / 97 }));
        });
        this.setState({ particles, particleKey: key });
      }
    }
  }
  finalizeState(context: LayerContext) {
    this.state.motion.removeEventListener("change", this.state.onEnvironmentChange);
    document.removeEventListener("visibilitychange", this.state.onEnvironmentChange);
    super.finalizeState(context);
  }
  renderLayers(): Layer[] {
    const { column, kind } = this.props;
    const { assets, failed, groups, particles } = this.state;
    if (!assets || failed) return [column.clone(this.getSubLayerProps({ id: "columns" }))];
    const weight = overviewWeight(this.context.viewport.zoom);
    const radius = column.props.radius;
    const scaled = (feature: PointFeature) => overviewScale(modelScale(feature, kind), radius, weight);
    const layers: Layer[] = groups.map((data, variant) => new assets.MeshLayer<PointFeature>({
      ...this.getSubLayerProps({ id: `mesh-${variant}` }), data,
      mesh: assets.meshes[variant], texture: assets.texture,
      hot: kind === "active", parameters: { cullMode: "none" },
      getPosition: feature => feature.geometry.coordinates as [number, number],
      getOrientation: feature => [0, hash(feature) % 360, 0], getScale: scaled,
      getColor: feature => kind === "seamount"
        ? feature.properties?.in_concession ? [245, 210, 0, 220] : [145, 205, 255, 200]
        : kind === "active" ? [255, 210, 160, isConfirmedVentStatus(feature.properties?.status) ? 235 : 120]
          : [150, 195, 235, 175],
      updateTriggers: { getScale: [radius, weight] }, onError: this.fail,
    }));
    if (kind === "active") {
      const active = groups[0] || [];
      const dimensions = overviewScale([360, 360, 1800], radius, weight);
      for (const inner of [false, true]) layers.unshift(new ScatterplotLayer<PointFeature>({
        ...this.getSubLayerProps({ id: inner ? "base-core" : "base-glow" }), data: active,
        pickable: false, autoHighlight: false, billboard: false,
        getPosition: feature => feature.geometry.coordinates as [number, number],
        getRadius: dimensions[0] * (inner ? 0.6 : 1.8),
        radiusMinPixels: inner ? 5 : 11, radiusMaxPixels: inner ? 12 : 23,
        getFillColor: feature => [255, inner ? 95 : 45, 15,
          isConfirmedVentStatus(feature.properties?.status) ? (inner ? 200 : 85) : (inner ? 100 : 40)],
        updateTriggers: { getRadius: [radius, weight] }, onError: this.fail,
      }));
      if (particles.length && !this.state.motion.matches && !document.hidden) layers.push(new ModelPlumeLayer<Particle>({
        ...this.getSubLayerProps({ id: "plume" }), data: particles,
        pickable: false, autoHighlight: false, billboard: true,
        getPosition: p => [...p.feature.geometry.coordinates.slice(0, 2), dimensions[2]] as [number, number, number],
        getRadius: dimensions[0], getLineWidth: p => p.phase,
        radiusMinPixels: 3, radiusMaxPixels: 32,
        getFillColor: p => [255, 145, 75, isConfirmedVentStatus(p.feature.properties?.status) ? 225 : 115],
        updateTriggers: { getPosition: [radius, weight], getRadius: [radius, weight] }, onError: this.fail,
      }));
    }
    return layers;
  }
}

export function createObjectModels(column: ColumnLayer, kind: ModelKind, props: Partial<LayerProps>): Layer {
  return new ObjectModelsLayer({ ...props, data: column.props.data as PointFeature[], column, kind });
}
